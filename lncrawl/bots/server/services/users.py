import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from jose import jwt
from passlib.context import CryptContext

from ..context import ServerContext
from ..exceptions import AppErrors
from ..models.pagination import Paginated
from ..models.user import (CreateRequest, LoginRequest, PasswordUpdateRequest,
                           UpdateRequest, User, UserRole, UserTier,
                           VerifiedEmail)
from ..utils.time_utils import current_timestamp

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx
        self._db = ctx.db
        self._passlib = CryptContext(
            schemes=['argon2'],
            deprecated='auto',
        )

    def _hash(self, plain_password: str) -> str:
        return self._passlib.hash(plain_password)

    def _check(self, plain: str, hashed: str) -> bool:
        return self._passlib.verify(plain, hashed)

    def prepare(self):
        email = self._ctx.config.server.admin_email
        password = self._ctx.config.server.admin_password
        
        user_data = self._db.users.find_one({"email": email})
        
        if not user_data:
            logger.info('Adding admin user')
            user = User(
                email=email,
                password=self._hash(password),
                name="Server Admin",
                role=UserRole.ADMIN,
                tier=UserTier.VIP,
            )
            self._db.users.insert_one(user.model_dump(by_alias=True))
        else:
            logger.info('Updating admin user')
            self._db.users.update_one(
                {"_id": user_data["_id"]},
                {"$set": {
                    "is_active": True,
                    "role": UserRole.ADMIN,
                    "tier": UserTier.VIP,
                    "password": self._hash(password),
                    "updated_at": current_timestamp()
                }}
            )

    def encode_token(
        self,
        payload: Dict[str, Any],
        expiry_minutes: Optional[int] = None,
    ) -> str:
        key = self._ctx.config.server.token_secret
        algorithm = self._ctx.config.server.token_algo
        default_expiry = self._ctx.config.server.token_expiry
        minutes = expiry_minutes if expiry_minutes else default_expiry
        payload['exp'] = datetime.now() + timedelta(minutes=minutes)
        return jwt.encode(payload, key, algorithm)

    def decode_token(self, token: str) -> Dict[str, Any]:
        try:
            key = self._ctx.config.server.token_secret
            algorithm = self._ctx.config.server.token_algo
            return jwt.decode(token, key, algorithm)
        except Exception as e:
            raise AppErrors.unauthorized from e

    def generate_token(
        self,
        user: User,
        expiry_minutes: Optional[int] = None,
    ) -> str:
        payload = {
            'uid': user.id,
            'scopes': [user.role, user.tier],
        }
        return self.encode_token(payload, expiry_minutes)

    def verify_token(self, token: str, required_scopes: List[str]) -> User:
        payload = self.decode_token(token)
        user_id = payload.get('uid')
        token_scopes = payload.get('scopes', [])
        if not user_id:
            raise AppErrors.unauthorized
        if any(scope not in token_scopes for scope in required_scopes):
            raise AppErrors.forbidden
        return self.get(user_id)

    def list(
        self,
        offset: int = 0,
        limit: int = 20,
        search: Optional[str] = None
    ) -> Paginated[User]:
        query = {}
        if search:
            query = {
                "$or": [
                    {"name": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}},
                    {"role": {"$regex": search, "$options": "i"}},
                    {"tier": {"$regex": search, "$options": "i"}},
                ]
            }

        total = self._db.users.count_documents(query)
        cursor = self._db.users.find(query).sort("created_at", 1).skip(offset).limit(limit)
        items = [User(**doc) for doc in cursor]

        return Paginated(
            total=total,
            offset=offset,
            limit=limit,
            items=items,
        )

    def get(self, user_id: str) -> User:
        data = self._db.users.find_one({"_id": user_id})
        if not data:
            raise AppErrors.no_such_user
        return User(**data)

    def verify(self, creds: LoginRequest) -> User:
        data = self._db.users.find_one({"email": creds.email})
        if not data:
            raise AppErrors.no_such_user
        user = User(**data)
        if not user.is_active:
            raise AppErrors.inactive_user
        if not self._check(creds.password, user.password):
            raise AppErrors.unauthorized
        return user

    def create(self, body: CreateRequest) -> User:
        if self._db.users.count_documents({"email": body.email}) > 0:
            raise AppErrors.user_exists
        
        user = User(
            name=body.name,
            email=body.email,
            role=body.role,
            tier=body.tier,
            password=self._hash(body.password),
        )
        self._db.users.insert_one(user.model_dump(by_alias=True))
        return user

    def update(self, user_id: str, body: UpdateRequest) -> bool:
        user_data = self._db.users.find_one({"_id": user_id})
        if not user_data:
            raise AppErrors.no_such_user

        update_data = {}
        if body.name is not None:
            update_data["name"] = body.name
        if body.password is not None:
            update_data["password"] = self._hash(body.password)
        if body.role is not None:
            update_data["role"] = body.role
        if body.tier is not None:
            update_data["tier"] = body.tier
        if body.is_active is not None:
            update_data["is_active"] = body.is_active

        if update_data:
            update_data["updated_at"] = current_timestamp()
            self._db.users.update_one({"_id": user_id}, {"$set": update_data})
            return True
        return False

    def change_password(self, user: User, body: PasswordUpdateRequest) -> bool:
        if not self._check(body.old_password, user.password):
            raise AppErrors.wrong_password
        request = UpdateRequest(password=body.new_password)
        return self.update(user.id, request)

    def remove(self, user_id: str) -> bool:
        result = self._db.users.delete_one({"_id": user_id})
        if result.deleted_count == 0:
            raise AppErrors.no_such_user
        return True

    def is_verified(self, email: str) -> bool:
        return self._db.verified_emails.find_one({"email": email}) is not None

    def set_verified(self, email: str) -> bool:
        if self.is_verified(email):
            return True
        
        entry = VerifiedEmail(email=email)
        self._db.verified_emails.insert_one(entry.model_dump())
        return True

    def send_otp(self, email: str):
        if self.is_verified(email):
            raise AppErrors.email_already_verified

        otp = str(secrets.randbelow(1000000)).zfill(6)
        self._ctx.mail.send_otp(email, otp)
        return self.encode_token({
            'otp': otp,
            'email': email,
        }, 5)

    def verify_otp(self, token: str, input_otp: str) -> bool:
        payload = self.decode_token(token)
        email = payload.get('email')
        if not email:
            raise AppErrors.not_found

        actual_otp = payload.get('otp')
        if actual_otp != input_otp:
            raise AppErrors.unauthorized

        self.set_verified(email)
        return True

    def send_password_reset_link(self, email: str) -> bool:
        data = self._db.users.find_one({"email": email})
        if not data:
            raise AppErrors.no_such_user
        
        user = User(**data)
        if not user.is_active:
            raise AppErrors.inactive_user
            
        token = self.generate_token(user, 5)
        base_url = self._ctx.config.server.base_url
        link = f'{base_url}/reset-password?token={token}&email={user.email}'

        self._ctx.mail.send_reset_password_link(email, link)
        return True