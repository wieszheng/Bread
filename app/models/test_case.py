#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Version  : Python 3.12
@Time     : 2024/9/9 23:57
@Author   : wiesZheng
@Software : PyCharm
"""
from typing import List

from sqlalchemy import INT, SMALLINT, TEXT, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models import BaseModel
from app.models.out_parameters import TestCaseOutParameters


class TestCase(BaseModel):
    """
    用例表
    """

    __tablename__ = "bread_testcase"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="主键ID"
    )
    name: Mapped[str] = mapped_column(String(32), index=True)
    request_type: Mapped[int] = mapped_column(
        INT, default=1, comment="请求类型 1: http 2: grpc 3: dubbo"
    )
    url: Mapped[str] = mapped_column(TEXT, nullable=False, comment="请求url")
    request_method: Mapped[str] = mapped_column(
        String(12), nullable=True, comment="请求方式, 如果非http可为空"
    )
    request_headers: Mapped[str] = mapped_column(TEXT, comment="请求头，可为空")
    base_path: Mapped[str] = mapped_column(String(24), comment="请求base_path")
    body: Mapped[str] = mapped_column(TEXT, comment="请求body")
    body_type: Mapped[int] = mapped_column(
        INT, comment="请求类型, 0: none 1: json 2: form 3: x-form 4: binary 5: GraphQL"
    )
    directory_id: Mapped[int] = mapped_column(INT, comment="所属目录")
    tag: Mapped[str] = mapped_column(String(64), comment="用例标签")
    status: Mapped[int] = mapped_column(
        INT, comment="用例状态: 1: 调试中 2: 暂时关闭 3: 正常运作"
    )
    priority: Mapped[str] = mapped_column(String(3), comment="用例优先级: P0-P4")
    case_type: Mapped[int] = mapped_column(
        SMALLINT, comment="0: 普通用例 1: 前置用例 2: 数据工厂"
    )
    out_parameters: List[TestCaseOutParameters | None] = mapped_column(default=None)
