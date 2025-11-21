import logging
import shutil
import time
from pathlib import Path
from threading import Event

from lncrawl.cloudscraper import AbortedException
from lncrawl.core.app import App
from lncrawl.core.download_chapters import restore_chapter_body
from lncrawl.core.metadata import (get_metadata_list, load_metadata,
                                   save_metadata)
from lncrawl.models import OutputFormat

from ..context import ServerContext
from ..models.enums import JobStatus, RunState
from ..models.job import Job
from ..models.novel import Artifact, Novel
from ..models.user import User
from ..utils.time_utils import current_timestamp
from .tier import ENABLED_FORMATS, SLOT_TIMEOUT_IN_SECOND


def microtask(job_id: str, signal=Event()) -> None:
    app = App()
    ctx = ServerContext()
    db = ctx.db
    logger = logging.getLogger(f'Job:{job_id}')

    def update_job(data):
        data['updated_at'] = current_timestamp()
        db.jobs.update_one({"_id": job_id}, {"$set": data})

    def get_job_data():
        return db.jobs.find_one({"_id": job_id})

    logger.info('=== Task begin ===')
    try:
        job_data = get_job_data()
        if not job_data:
            logger.error("Job not found")
            return
        job = Job(**job_data)

        #
        # Status: COMPLETED
        #
        if job.status == JobStatus.COMPLETED:
            logger.error('Job is already done')
            update_job({}) # triggers updated_at
            return

        #
        # State: SUCCESS, FAILED, CANCELED
        #
        if job.run_state in [
            RunState.FAILED,
            RunState.SUCCESS,
            RunState.CANCELED
        ]:
            update_job({'status': JobStatus.COMPLETED})
            return

        # State: PENDING
        #
        if job.status == JobStatus.PENDING:
            update_job({
                'run_state': RunState.FETCHING_NOVEL,
                'status': JobStatus.RUNNING
            })
            logger.info('Job started')
            job.run_state = RunState.FETCHING_NOVEL

        #
        # Prepare user, novel, app, crawler
        #
        logger.info('Prepare required data')
        user_data = db.users.find_one({"_id": job.user_id})
        if not user_data:
            update_job({
                'error': 'User is not available',
                'status': JobStatus.COMPLETED,
                'run_state': RunState.FAILED
            })
            return
        user = User(**user_data)

        novel_data = db.novels.find_one({"_id": job.novel_id})
        if not novel_data:
            update_job({
                'error': 'Novel is not available',
                'status': JobStatus.COMPLETED,
                'run_state': RunState.FAILED
            })
            return
        novel = Novel(**novel_data)

        logger.info('Initializing crawler')
        app.user_input = job.url
        app.output_formats = {x: True for x in ENABLED_FORMATS[user.tier]}
        app.output_formats[OutputFormat.json] = True
        app.prepare_search()

        crawler = app.crawler
        if not crawler:
            update_job({
                'error': 'No crawler available for this novel',
                'status': JobStatus.COMPLETED,
                'run_state': RunState.FAILED
            })
            return

        crawler.scraper.signal = signal  # type:ignore

        #
        # State: FETCHING_NOVEL
        #
        if job.run_state == RunState.FETCHING_NOVEL:
            logger.info('Fetching novel info')

            if job.started_at and current_timestamp() - job.started_at > 3600 * 1000:
                raise Exception('Timeout fetching novel info')

            app.get_novel_info()

            update_job({
                'progress': round(app.progress),
                'run_state': RunState.FETCHING_CONTENT
            })
            job.progress = round(app.progress)
            job.run_state = RunState.FETCHING_CONTENT

            db.novels.update_one(
                {"_id": novel.id},
                {"$set": {
                    "orphan": False,
                    "title": crawler.novel_title,
                    "cover": crawler.novel_cover,
                    "authors": crawler.novel_author,
                    "synopsis": crawler.novel_synopsis,
                    "tags": crawler.novel_tags or [],
                    "volume_count": len(crawler.volumes),
                    "chapter_count": len(crawler.chapters),
                    "updated_at": current_timestamp()
                }}
            )
            
            # refresh novel object
            novel_data = db.novels.find_one({"_id": novel.id})
            novel = Novel(**novel_data)

            logger.info(f'Novel: {novel}')
            return

        #
        # Restore session
        #
        logger.info('Restoring session')
        if novel.orphan or not novel.title:
            update_job({
                'error': 'Failed to fetch novel',
                'status': JobStatus.COMPLETED,
                'run_state': RunState.FAILED
            })
            return

        crawler.novel_url = novel.url
        crawler.novel_title = novel.title
        app.prepare_novel_output_path()

        logger.info(f'Checking metadata file: {app.output_path}')
        for meta in get_metadata_list(app.output_path):
            if meta.novel and meta.session and meta.novel.url == novel.url:
                logger.info('Loading session from metadata')
                load_metadata(app, meta)
                break  # found matching metadata
        else:
            # did not find any matching metadata
            update_job({
                'error': 'Failed to restore metadata',
                'status': JobStatus.COMPLETED,
                'run_state': RunState.FAILED
            })
            return

        extra = dict(novel.extra)
        extra['output_path'] = app.output_path
        db.novels.update_one(
            {"_id": novel.id},
            {"$set": {"extra": extra}}
        )

        #
        # State: FETCHING_CONTENT
        #
        if job.run_state == RunState.FETCHING_CONTENT:
            app.chapters = crawler.chapters
            logger.info(f'Fetching ({len(app.chapters)} chapters)')

            done = False
            last_report = 0.0
            start_time = time.time()
            timeout = SLOT_TIMEOUT_IN_SECOND[user.tier]
            for _ in app.start_download(signal):
                cur_time = time.time()
                if cur_time - start_time > timeout:
                    break
                if job.progress > round(app.progress):
                    logger.info('Failed to fetch some content')
                    done = True
                    break
                if cur_time - last_report > 5:
                    job.progress = round(app.progress)
                    last_report = cur_time
                    update_job({'progress': job.progress})
            else:
                done = True

            if done:
                app.fetch_chapter_progress = 100
                app.fetch_images_progress = 100
                save_metadata(app)
                if not signal.is_set():
                    logger.info('Fetch content completed')
                    update_job({'run_state': RunState.CREATING_ARTIFACTS})
                    job.run_state = RunState.CREATING_ARTIFACTS

            update_job({'progress': round(app.progress)})
            return

        logger.info('Restoring chapter contents')
        app.chapters = crawler.chapters
        restore_chapter_body(app)

        logger.info('Restoring job artifacts')
        for doc in ctx.jobs.get_artifacts(job_id):
            artifact = Artifact(**doc)
            app.generated_archives[artifact.format] = artifact.output_file
            logger.info(f'Artifact [{artifact.format}]: {artifact.output_file}')

        #
        # State: CREATING_ARTIFACTS
        #
        if job.run_state == RunState.CREATING_ARTIFACTS:
            logger.info('Creating artifacts')
            for fmt, archive_file in app.bind_books(signal):
                job.progress = round(app.progress)
                update_job({'progress': job.progress})
                
                artifact = Artifact(
                    format=fmt,
                    job_id=job.id,
                    novel_id=novel.id,
                    output_file=archive_file,
                )
                ctx.artifacts.upsert(artifact)
                logger.info(f'Artifact [{fmt}]: {archive_file}')
                return  # bind one at a time

            # remove output folders (except json)
            for fmt in OutputFormat:
                if str(fmt) != str(OutputFormat.json):
                    output = Path(app.output_path) / fmt
                    shutil.rmtree(output, ignore_errors=True)

            logger.info('Success!')
            update_job({
                'progress': 100,
                'status': JobStatus.COMPLETED,
                'run_state': RunState.SUCCESS
            })

            if ctx.users.is_verified(user.email):
                try:
                    detail = ctx.jobs.get(job_id)
                    ctx.mail.send_job_success(user.email, detail)
                    logger.error(f'Success report was sent to <{user.email}>')
                except Exception as e:
                    logger.error('Failed to email success report', e)

    except AbortedException:
        pass

    except Exception as e:
        logger.exception('Job failed', exc_info=True)
        job_data = get_job_data()
        if job_data and not job_data.get('error'):
            update_job({
                'status': JobStatus.COMPLETED,
                'run_state': RunState.FAILED,
                'error': str(e)
            })

    finally:
        # DB closing is handled by context cleanup or global client management
        logger.info('=== Task end ===')