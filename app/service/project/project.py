#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Version  : Python 3.12
@Time     : 2024/8/22 22:55
@Author   : wiesZheng
@Software : PyCharm
"""
import uuid
from typing import Annotated

from fastapi import File, Path, Request, UploadFile

from app.commons.response.response_code import CustomErrorCode
from app.commons.response.response_schema import ResponseBase, ResponseModel
from app.core.client.miNio import minio_client
from app.crud.helper import compute_offset
from app.crud.project.project import ProjectCRUD
from app.exceptions.errors import CustomException
from app.models.project import ProjectModel
from app.models.user import UserModel
from app.schemas.auth.user import UserInfoSchemaBase
from app.schemas.project.project import (
    GetCurrentProjectInfoDetail,
    GetProjectInfo,
    ProjectSchemaBase,
    UpdateProjectParam,
)
from config import settings


class ProjectService:

    @staticmethod
    async def get_projects(
        page: int,
        page_size: int,
    ) -> ResponseModel:

        result = await ProjectCRUD.get_multi_joined(
            limit=page_size,
            offset=compute_offset(page, page_size),
            sort_columns=["id"],
            sort_orders=["desc"],
            join_model=UserModel,
            schema_to_select=GetCurrentProjectInfoDetail,
            join_schema_to_select=UserInfoSchemaBase,
            is_deleted=False,
            join_on=ProjectModel.created_by == UserModel.id,
            return_as_model=True,
        )
        return await ResponseBase.success(
            result={**result, "page": page, "page_size": page_size}
        )

    @staticmethod
    async def create_project(request: Request, obj: ProjectSchemaBase) -> ResponseModel:
        """
        创建项目
        :return:
        """
        input_name = await ProjectCRUD.exists(name=obj.name)
        if input_name:
            raise CustomException(CustomErrorCode.PROJECT_NAME_EXIST)
        if obj.owner:
            obj.owner = request.user.id
        project_data = await ProjectCRUD.create(obj=obj, created_by=request.user.id)
        data = GetProjectInfo.model_validate(project_data).model_dump()
        return await ResponseBase.success(result=data)

    @staticmethod
    async def update_project(
        request: Request, obj: UpdateProjectParam
    ) -> ResponseModel:
        """
        更新项目
        :param request:
        :param obj:
        :return:
        """
        input_id = await ProjectCRUD.get(id=obj.id)
        if not input_id:
            raise CustomException(CustomErrorCode.PROJECT_ID_EXIST)
        if input_id["owner"] != request.user.id and request.user.role < settings.ADMIN:
            raise CustomException(CustomErrorCode.PROJECT_No_PERMISSION)
        await ProjectCRUD.update(
            obj={**obj.model_dump(), "updated_by": request.user.id}
        )
        return await ResponseBase.success()

    @staticmethod
    async def update_project_avatar(
        request: Request,
        project_id: Annotated[str, Path(...)],
        avatar: UploadFile = File(..., description="上传的头像文件"),
    ) -> ResponseModel:
        """
        更新项目头像
        :param request:
        :param project_id:
        :param avatar:
        :return:
        """
        # 生成随机文件名
        input_id = await ProjectCRUD.get(id=project_id)
        if not input_id:
            raise CustomException(CustomErrorCode.PROJECT_ID_EXIST)
        if input_id["owner"] != request.user.id and request.user.role < settings.ADMIN:
            raise CustomException(CustomErrorCode.PROJECT_No_PERMISSION)
        random_suffix = str(uuid.uuid4()).replace("-", "")
        object_name = (
            f"{request.user.id}/{random_suffix}.{avatar.filename.split('.')[-1]}"
        )
        minio_client.upload_file(
            object_name, avatar.file, content_type=avatar.content_type
        )

        avatar_url = minio_client.pre_signature_get_object_url(object_name)
        await ProjectCRUD.update(
            obj={"avatar": avatar_url.split("?", 1)[0], "updated_by": request.user.id},
            id=project_id,
        )

        return await ResponseBase.success()

    @staticmethod
    async def is_del_project(
        request: Request, project_id: Annotated[int, ...]
    ) -> ResponseModel:
        input_id = await ProjectCRUD.get(id=project_id)
        if not input_id:
            raise CustomException(CustomErrorCode.PROJECT_ID_EXIST)
        if input_id["owner"] != request.user.id and request.user.role != settings.ADMIN:
            raise CustomException(CustomErrorCode.PROJECT_No_PERMISSION)
        await ProjectCRUD.delete(id=project_id)
        return await ResponseBase.success()

    @staticmethod
    async def allocation_project_role():
        pass

    @staticmethod
    async def update_project_role():
        pass

    @staticmethod
    async def del_project_role():
        pass
