#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Version  : Python 3.12
@Time     : 2024/8/17 13:01
@Author   : wiesZheng
@Software : PyCharm
"""
from typing import Any

from fastapi import Request, Response
from fastapi.security.utils import get_authorization_scheme_param
from loguru import logger
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
)
from starlette.requests import HTTPConnection

from app.commons.response.response_code import StandardResponseCode
from app.commons.response.response_schema import ApiResponse
from app.core.security import Jwt
from app.exceptions.errors import TokenError
from app.schemas.auth.user import CurrentUserIns


class _AuthenticationError(AuthenticationError):
    """重写内部认证错误类"""

    def __init__(
        self,
        *,
        code: int = None,
        message: str = None,
        headers: dict[str, Any] | None = None
    ):
        self.code = code
        self.message = message
        self.headers = headers


class JwtAuthMiddleware(AuthenticationBackend):
    """JWT 认证中间件"""

    @staticmethod
    def auth_exception_handler(
        conn: HTTPConnection, exc: _AuthenticationError
    ) -> Response:
        """覆盖内部认证错误处理"""

        return ApiResponse(
            http_status_code=StandardResponseCode.HTTP_401,
            success=False,
            code=StandardResponseCode.HTTP_401,
            message=exc.message,
        )

    async def authenticate(
        self, request: Request
    ) -> tuple[AuthCredentials, CurrentUserIns] | None:
        token = request.headers.get("Authorization")
        if not token:
            return

        scheme, token = get_authorization_scheme_param(token)
        if scheme.lower() != "bearer":
            return
        try:
            sub = await Jwt.decode_jwt_token(token)
            current_user = await Jwt.get_current_user(sub)
            user = CurrentUserIns.model_validate(current_user)
        except TokenError as exc:
            raise _AuthenticationError(
                message=exc.message, headers={"WWW-Authenticate": "Bearer"}
            )
        except Exception as e:
            logger.exception(e)
            raise _AuthenticationError(
                code=getattr(e, "code", 500),
                message=getattr(e, "message", "Internal Server Error"),
            )

        return AuthCredentials(["authenticated"]), user
