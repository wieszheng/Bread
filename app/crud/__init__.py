# !/usr/bin/env python
# -*- coding:utf-8 -*-
"""
@Version  : Python 3.12
@Time     : 2024/8/9 15:07
@Author   : wiesZheng
@Software : PyCharm
"""
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Optional, Callable, Union, Dict, Sequence, Type

from loguru import logger
from pydantic import BaseModel, ValidationError
from sqlalchemy import (
    Insert,
    Result,
    and_,
    select,
    update,
    delete,
    func,
    inspect,
    asc,
    desc,
    or_,
    column,
    Column,
    Select,
    Row,
    Join,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm.util import AliasedClass
from sqlalchemy.sql.elements import BinaryExpression, ColumnElement
from app.crud.helper import JoinConfig
from app.crud.types import ModelType, CreateSchemaType, UpdateSchemaType
from app.exceptions.errors import DBError
from app.models import async_session_maker


def with_session(method):
    """
    兼容事务
    Args:
        method: orm 的 crud
    Notes:
        方法中没有带事务连接则，则构造
    Returns:
    """

    @wraps(method)
    async def wrapper(cls, *args, **kwargs):
        try:
            session = kwargs.get("session") or None
            if session:
                return await method(cls, *args, **kwargs)
            else:
                async with async_session_maker() as session:
                    async with session.begin():
                        kwargs["session"] = session
                        return await method(cls, *args, **kwargs)
        except Exception as e:
            import traceback

            logger.error(
                f"操作Model：{cls.__model__.__name__}\n"
                f"方法：{method.__name__}\n"
                f"参数：args：{[*args]}, kwargs：{kwargs}\n"
                f"错误：{e}\n"
            )
            # logger.error(traceback.format_exc())
            raise DBError(f"操作数据库异常：{method.__name__}: {e}")

    return wrapper


def _extract_matching_columns_from_schema(
        model: Union[ModelType, AliasedClass],
        schema: Optional[type[BaseModel]],
        prefix: Optional[str] = None,
        alias: Optional[AliasedClass] = None,
        use_temporary_prefix: Optional[bool] = False,
        temp_prefix: Optional[str] = "joined__",
) -> list[Any]:
    if not hasattr(model, "__table__"):  # pragma: no cover
        raise AttributeError(f"{model.__name__} does not have a '__table__' attribute.")

    model_or_alias = alias if alias else model
    columns = []
    temp_prefix = (
        temp_prefix if use_temporary_prefix and temp_prefix is not None else ""
    )
    if schema:
        for field in schema.model_fields.keys():
            if hasattr(model_or_alias, field):
                column = getattr(model_or_alias, field)
                if prefix is not None or use_temporary_prefix:
                    column_label = (
                        f"{temp_prefix}{prefix}{field}"
                        if prefix
                        else f"{temp_prefix}{field}"
                    )
                    column = column.label(column_label)
                columns.append(column)
    else:
        for column in model.__table__.c:
            column = getattr(model_or_alias, column.key)
            if prefix is not None or use_temporary_prefix:
                column_label = (
                    f"{temp_prefix}{prefix}{column.key}"
                    if prefix
                    else f"{temp_prefix}{column.key}"
                )
                column = column.label(column_label)
            columns.append(column)

    return columns


def _get_primary_key(
        model: ModelType,
) -> Union[str, None]:  # pragma: no cover
    key: Optional[str] = _get_primary_keys(model)[0].name
    return key


def _get_primary_keys(
        model: ModelType,
) -> Sequence[Column]:
    """Get the primary key of a SQLAlchemy model."""
    inspector_result = inspect(model)
    if inspector_result is None:  # pragma: no cover
        raise ValueError("Model inspection failed, resulting in None.")
    primary_key_columns: Sequence[Column] = inspector_result.mapper.primary_key

    return primary_key_columns


def _handle_one_to_many(nested_data, nested_key, nested_field, value):
    if nested_key not in nested_data or not isinstance(nested_data[nested_key], list):
        nested_data[nested_key] = []

    if not nested_data[nested_key] or nested_field in nested_data[nested_key][-1]:
        nested_data[nested_key].append({nested_field: value})
    else:
        nested_data[nested_key][-1][nested_field] = value

    return nested_data


def _handle_one_to_one(nested_data, nested_key, nested_field, value):
    if nested_key not in nested_data or not isinstance(nested_data[nested_key], dict):
        nested_data[nested_key] = {}
    nested_data[nested_key][nested_field] = value
    return nested_data


def _nest_join_data(
        data: dict,
        join_definitions: list[JoinConfig],
        temp_prefix: str = "joined__",
        nested_data: Optional[dict[str, Any]] = None,
) -> dict:
    if nested_data is None:
        nested_data = {}

    for key, value in data.items():
        nested = False
        for join in join_definitions:
            join_prefix = join.join_prefix or ""
            full_prefix = f"{temp_prefix}{join_prefix}"

            if isinstance(key, str) and key.startswith(full_prefix):
                nested_key = (
                    join_prefix.rstrip("_") if join_prefix else join.model.__tablename__
                )
                nested_field = key[len(full_prefix):]

                if join.relationship_type == "one-to-many":
                    nested_data = _handle_one_to_many(
                        nested_data, nested_key, nested_field, value
                    )
                else:
                    nested_data = _handle_one_to_one(
                        nested_data, nested_key, nested_field, value
                    )

                nested = True
                break

        if not nested:
            stripped_key = (
                key[len(temp_prefix):]
                if isinstance(key, str) and key.startswith(temp_prefix)
                else key
            )
            if nested_data is None:  # pragma: no cover
                nested_data = {}

            nested_data[stripped_key] = value

    if nested_data is None:  # pragma: no cover
        nested_data = {}

    for join in join_definitions:
        join_primary_key = _get_primary_key(join.model)
        nested_key = (
            join.join_prefix.rstrip("_")
            if join.join_prefix
            else join.model.__tablename__
        )
        if join.relationship_type == "one-to-many" and nested_key in nested_data:
            if isinstance(nested_data.get(nested_key, []), list):
                if any(
                        item[join_primary_key] is None for item in nested_data[nested_key]
                ):
                    nested_data[nested_key] = []

        if nested_key in nested_data and isinstance(nested_data[nested_key], dict):
            if (
                    join_primary_key in nested_data[nested_key]
                    and nested_data[nested_key][join_primary_key] is None
            ):
                nested_data[nested_key] = None

    assert nested_data is not None, "Couldn't nest the data."
    return nested_data


class BaseCRUD:
    __model__: Type[ModelType] = None
    is_deleted_column: str = "is_deleted"
    deleted_at_column: str = "deleted_at"
    updated_at_column: str = "updated_at"

    _SUPPORTED_FILTERS = {
        "gt": lambda column: column.__gt__,
        "lt": lambda column: column.__lt__,
        "gte": lambda column: column.__ge__,
        "lte": lambda column: column.__le__,
        "ne": lambda column: column.__ne__,
        "is": lambda column: column.is_,
        "is_not": lambda column: column.is_not,
        "like": lambda column: column.like,
        "notlike": lambda column: column.notlike,
        "ilike": lambda column: column.ilike,
        "notilike": lambda column: column.notilike,
        "startswith": lambda column: column.startswith,
        "endswith": lambda column: column.endswith,
        "contains": lambda column: column.contains,
        "match": lambda column: column.match,
        "between": lambda column: column.between,
        "in": lambda column: column.in_,
        "not_in": lambda column: column.not_in,
    }

    @classmethod
    def _get_sqlalchemy_filter(
            cls,
            operator: str,
            value: Any,
    ) -> Optional[Callable[[str], Callable]]:
        if operator in {"in", "not_in", "between"}:
            if not isinstance(value, (tuple, list, set)):
                raise ValueError(f"<{operator}> filter must be tuple, list or set")
        return cls._SUPPORTED_FILTERS.get(operator)

    @classmethod
    def _parse_filters(
            cls, model: Optional[Union[type[ModelType], AliasedClass]] = None, **kwargs
    ) -> list[ColumnElement]:
        model = model or cls.__model__
        filters = []

        for key, value in kwargs.items():
            if "__" in key:
                field_name, op = key.rsplit("__", 1)
                column_ = getattr(model, field_name, None)
                if column_ is None:
                    raise ValueError(f"Invalid filter column: {field_name}")
                if op == "or":
                    or_filters = [
                        sqlalchemy_filter(column_)(or_value)
                        for or_key, or_value in value.items()
                        if (
                               sqlalchemy_filter := cls._get_sqlalchemy_filter(
                                   or_key, value
                               )
                           )
                           is not None
                    ]
                    filters.append(or_(*or_filters))
                else:
                    sqlalchemy_filter = cls._get_sqlalchemy_filter(op, value)
                    if sqlalchemy_filter:
                        filters.append(sqlalchemy_filter(column_)(value))
            else:
                column_ = getattr(model, key, None)
                if column_ is not None:
                    if value is not None:
                        filters.append(column_ == value)

        return filters

    @classmethod
    def _apply_sorting(
            cls,
            stmt: Select,
            sort_columns: Union[str, list[str]],
            sort_orders: Optional[Union[str, list[str]]] = None,
    ) -> Select:

        if sort_orders and not sort_columns:
            raise ValueError("Sort orders provided without corresponding sort columns.")

        if sort_columns:
            if not isinstance(sort_columns, list):
                sort_columns = [sort_columns]

            if sort_orders:
                if not isinstance(sort_orders, list):
                    sort_orders = [sort_orders] * len(sort_columns)
                if len(sort_columns) != len(sort_orders):
                    raise ValueError(
                        "The length of sort_columns and sort_orders must match."
                    )

                for idx, order in enumerate(sort_orders):
                    if order not in ["asc", "desc"]:
                        raise ValueError(
                            f"Invalid sort order: {order}. Only 'asc' or 'desc' are allowed."
                        )

            validated_sort_orders = (
                ["asc"] * len(sort_columns) if not sort_orders else sort_orders
            )

            for idx, column_name in enumerate(sort_columns):
                column = getattr(cls.__model__, column_name, None)
                if not column:
                    raise ValueError(f"Invalid column name: {column_name}")

                order = validated_sort_orders[idx]
                stmt = stmt.order_by(asc(column) if order == "asc" else desc(column))

        return stmt

    @classmethod
    def _prepare_and_apply_joins(
            cls,
            stmt: Select,
            joins_config: list[JoinConfig],
            use_temporary_prefix: bool = False,
    ):

        for join in joins_config:
            model = join.alias or join.model
            join_select = _extract_matching_columns_from_schema(
                model,
                join.schema_to_select,
                join.join_prefix,
                join.alias,
                use_temporary_prefix,
            )
            joined_model_filters = cls._parse_filters(
                model=model, **(join.filters or {})
            )

            if join.join_type == "left":
                stmt = stmt.outerjoin(model, join.join_on).add_columns(*join_select)
            elif join.join_type == "inner":
                stmt = stmt.join(model, join.join_on).add_columns(*join_select)
            else:  # pragma: no cover
                raise ValueError(f"Unsupported join type: {join.join_type}.")
            if joined_model_filters:
                stmt = stmt.filter(*joined_model_filters)

        return stmt

    @classmethod
    @with_session
    async def create(
            cls, *, obj: CreateSchemaType, commit: bool = True, session: AsyncSession = None, **kwargs: Any
    ) -> ModelType:

        object_dict = obj.model_dump()
        object_mt: ModelType = cls.__model__(**object_dict, **kwargs)
        session.add(object_mt)
        if commit:
            await session.commit()
        return object_mt

    @classmethod
    async def select(
            cls,
            *,
            schema_to_select: Optional[type[BaseModel]] = None,
            sort_columns: Optional[Union[str, list[str]]] = None,
            sort_orders: Optional[Union[str, list[str]]] = None,
            **kwargs: Any,
    ) -> Select:
        to_select = _extract_matching_columns_from_schema(
            model=cls.__model__, schema=schema_to_select
        )
        filters = cls._parse_filters(**kwargs)
        stmt = select(*to_select).filter(*filters)

        if sort_columns:
            stmt = cls._apply_sorting(stmt, sort_columns, sort_orders)
        return stmt

    @classmethod
    @with_session
    async def get(
            cls,
            *,
            schema_to_select: Optional[type[BaseModel]] = None,
            return_as_model: bool = False,
            one_or_none: bool = False,
            session: AsyncSession = None,
            **kwargs: Any,
    ) -> Optional[Union[dict, BaseModel]]:
        stmt = await cls.select(schema_to_select=schema_to_select, **kwargs)

        db_row = await session.execute(stmt)
        result: Optional[Row] = db_row.one_or_none() if one_or_none else db_row.first()
        if result is None:
            return None
        out: dict = dict(result._mapping)
        if not return_as_model:
            return out
        if not schema_to_select:
            raise ValueError(
                "schema_to_select must be provided when return_as_model is True."
            )
        return schema_to_select(**out)

    @classmethod
    def _get_pk_dict(cls, instance):
        return {
            pk.name: getattr(instance, pk.name)
            for pk in _get_primary_keys(cls.__model__)
        }

    @classmethod
    async def upsert(
            cls,
            *,
            instance: Union[UpdateSchemaType, CreateSchemaType],
            schema_to_select: Optional[type[BaseModel]] = None,
            return_as_model: bool = False,
    ) -> Union[BaseModel, Dict[str, Any], None]:
        _pks = cls._get_pk_dict(instance)
        schema_to_select = schema_to_select or type(instance)
        db_instance = await cls.get(
            schema_to_select=schema_to_select,
            return_as_model=return_as_model,
            **_pks,
        )
        if db_instance is None:
            db_instance = await cls.create(instance)  # type: ignore
            db_instance = schema_to_select.model_validate(
                db_instance, from_attributes=True
            )
        else:
            await cls.update(db, instance)  # type: ignore
            db_instance = await cls.get(
                schema_to_select=schema_to_select,
                return_as_model=return_as_model,
                **_pks,
            )

        return db_instance

    @classmethod
    @with_session
    async def exists(cls, session: AsyncSession = None, **kwargs: Any) -> bool:
        filters = cls._parse_filters(**kwargs)
        stmt = select(cls.__model__).filter(*filters).limit(1)

        result = await session.execute(stmt)
        return result.first() is not None

    @classmethod
    @with_session
    async def count(
            cls,
            *,
            session: AsyncSession = None,
            **kwargs: Any,
    ) -> int:
        filters = cls._parse_filters(**kwargs)
        if filters:
            count_query = (
                select(func.count()).select_from(cls.__model__).filter(*filters)
            )
        else:
            count_query = select(func.count()).select_from(cls.__model__)

        total_count = await session.scalar(count_query)
        return total_count

    @classmethod
    @with_session
    async def get_multi(
            cls,
            *,
            offset: int = 0,
            limit: Optional[int] = 100,
            schema_to_select: Optional[type[BaseModel]] = None,
            sort_columns: Optional[Union[str, list[str]]] = None,
            sort_orders: Optional[Union[str, list[str]]] = None,
            return_as_model: bool = False,
            return_total_count: bool = True,
            session: AsyncSession = None,
            **kwargs: Any,
    ) -> dict[str, Any]:

        if (limit is not None and limit < 0) or offset < 0:
            raise ValueError("Limit and offset must be non-negative.")

        stmt = await cls.select(
            schema_to_select=schema_to_select,
            sort_columns=sort_columns,
            sort_orders=sort_orders,
            **kwargs,
        )

        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        data = [dict(row) for row in result.mappings()]

        response: dict[str, Any] = {"data": data}

        if return_total_count:
            total_count = await cls.count(**kwargs)
            response["total_count"] = total_count

        if return_as_model:
            if not schema_to_select:
                raise ValueError(
                    "schema_to_select must be provided when return_as_model is True."
                )
            try:
                model_data = [schema_to_select(**row) for row in data]
                response["data"] = model_data
            except ValidationError as e:
                raise ValueError(
                    f"Data validation error for schema {schema_to_select.__name__}: {e}"
                )

        return response

    @classmethod
    @with_session
    async def get_joined(
            cls,
            *,
            schema_to_select: Optional[type[BaseModel]] = None,
            join_model: Optional[ModelType] = None,
            join_on: Optional[Union[Join, BinaryExpression]] = None,
            join_prefix: Optional[str] = None,
            join_schema_to_select: Optional[type[BaseModel]] = None,
            join_type: str = "left",
            alias: Optional[AliasedClass] = None,
            join_filters: Optional[dict] = None,
            joins_config: Optional[list[JoinConfig]] = None,
            nest_joins: bool = False,
            relationship_type: Optional[str] = None,
            session: AsyncSession = None,
            **kwargs: Any,
    ) -> Optional[dict[str, Any]]:

        if joins_config and (
                join_model or join_prefix or join_on or join_schema_to_select or alias
        ):
            raise ValueError(
                "Cannot use both single join parameters and joins_config simultaneously."
            )
        elif not joins_config and not join_model:
            raise ValueError("You need one of join_model or joins_config.")

        primary_select = _extract_matching_columns_from_schema(
            model=cls.__model__,
            schema=schema_to_select,
        )
        stmt: Select = select(*primary_select).select_from(cls.__model__)

        join_definitions = joins_config if joins_config else []
        if join_model:
            join_definitions.append(
                JoinConfig(
                    model=join_model,
                    join_on=join_on,
                    join_prefix=join_prefix,
                    schema_to_select=join_schema_to_select,
                    join_type=join_type,
                    alias=alias,
                    filters=join_filters,
                    relationship_type=relationship_type,
                )
            )

        stmt = cls._prepare_and_apply_joins(
            stmt=stmt, joins_config=join_definitions, use_temporary_prefix=nest_joins
        )
        primary_filters = cls._parse_filters(**kwargs)
        if primary_filters:
            stmt = stmt.filter(*primary_filters)

        db_rows = await session.execute(stmt)
        if any(join.relationship_type == "one-to-many" for join in join_definitions):
            if nest_joins is False:  # pragma: no cover
                raise ValueError(
                    "Cannot use one-to-many relationship with nest_joins=False"
                )
            results = db_rows.fetchall()
            data_list = [dict(row._mapping) for row in results]
        else:
            result = db_rows.first()
            if result is not None:
                data_list = [dict(result._mapping)]
            else:
                data_list = []

        if data_list:
            if nest_joins:
                nested_data: dict = {}
                for data in data_list:
                    nested_data = _nest_join_data(
                        data,
                        join_definitions,
                        nested_data=nested_data,
                    )
                return nested_data
            return data_list[0]

        return None

    @classmethod
    def _as_single_response(
            cls,
            db_row: Result,
            schema_to_select: Optional[type[BaseModel]] = None,
            return_as_model: bool = False,
            one_or_none: bool = False,
    ) -> Optional[Union[dict, BaseModel]]:
        result: Optional[Row] = db_row.one_or_none() if one_or_none else db_row.first()
        if result is None:  # pragma: no cover
            return None
        out: dict = dict(result._mapping)
        if not return_as_model:
            return out
        if not schema_to_select:  # pragma: no cover
            raise ValueError(
                "schema_to_select must be provided when return_as_model is True."
            )
        return schema_to_select(**out)

    @classmethod
    def _as_multi_response(
            cls,
            db_row: Result,
            schema_to_select: Optional[type[BaseModel]] = None,
            return_as_model: bool = False,
    ) -> dict:
        data = [dict(row) for row in db_row.mappings()]

        response: dict[str, Any] = {"data": data}

        if return_as_model:
            if not schema_to_select:  # pragma: no cover
                raise ValueError(
                    "schema_to_select must be provided when return_as_model is True."
                )
            try:
                model_data = [schema_to_select(**row) for row in data]
                response["data"] = model_data
            except ValidationError as e:  # pragma: no cover
                raise ValueError(
                    f"Data validation error for schema {schema_to_select.__name__}: {e}"
                )

        return response

    @classmethod
    @with_session
    async def update(
            cls,
            *,
            obj: Union[UpdateSchemaType, dict[str, Any]],
            allow_multiple: bool = False,
            commit: bool = True,
            return_columns: Optional[list[str]] = None,
            schema_to_select: Optional[type[BaseModel]] = None,
            return_as_model: bool = False,
            one_or_none: bool = False,
            session: AsyncSession = None,
            **kwargs: Any,
    ) -> Optional[Union[dict, BaseModel]]:

        if not allow_multiple and (total_count := await cls.count(**kwargs)) > 1:
            raise ValueError(
                f"Expected exactly one record to update, found {total_count}."
            )
        if isinstance(obj, dict):
            update_data = obj
        else:
            update_data = obj.model_dump(exclude_unset=True)

        updated_at_col = getattr(cls.__model__, cls.updated_at_column, None)
        if updated_at_col:
            update_data[cls.updated_at_column] = datetime.now()

        update_data_keys = set(update_data.keys())
        model_columns = {column_.name for column_ in inspect(cls.__model__).c}
        extra_fields = update_data_keys - model_columns
        if extra_fields:
            raise ValueError(f"Extra fields provided: {extra_fields}")

        filters = cls._parse_filters(**kwargs)
        stmt = update(cls.__model__).filter(*filters).values(update_data)

        if return_as_model:
            return_columns = [col.key for col in cls.__model__.__table__.columns]

        if return_columns:
            stmt = stmt.returning(*[column(name) for name in return_columns])
            db_row = await session.execute(stmt)
            if allow_multiple:
                return cls._as_multi_response(
                    db_row,
                    schema_to_select=schema_to_select,
                    return_as_model=return_as_model,
                )
            return cls._as_single_response(
                db_row,
                schema_to_select=schema_to_select,
                return_as_model=return_as_model,
                one_or_none=one_or_none,
            )

        await session.execute(stmt)
        if commit:
            await session.commit()
        return None

    @classmethod
    @with_session
    async def db_delete(
            cls,
            allow_multiple: bool = False,
            commit: bool = True,
            session: AsyncSession = None,
            **kwargs: Any,
    ) -> None:
        if not allow_multiple and (total_count := await cls.count(**kwargs)) > 1:
            raise ValueError(
                f"Expected exactly one record to delete, found {total_count}."
            )

        filters = cls._parse_filters(**kwargs)
        stmt = delete(cls.__model__).filter(*filters)
        await session.execute(stmt)
        if commit:
            await session.commit()

    @classmethod
    @with_session
    async def delete(
            cls,
            db_row: Optional[Row] = None,
            allow_multiple: bool = False,
            commit: bool = True,
            session: AsyncSession = None,
            **kwargs: Any,
    ) -> None:
        filters = cls._parse_filters(**kwargs)
        if db_row:
            if hasattr(db_row, cls.is_deleted_column) and hasattr(
                    db_row, cls.deleted_at_column
            ):
                setattr(db_row, cls.is_deleted_column, True)
                setattr(db_row, cls.deleted_at_column, datetime.now())
                if commit:
                    await session.commit()
            else:
                await session.delete(db_row)
            if commit:
                await session.commit()
            return

        total_count = await cls.count(**kwargs)
        if total_count == 0:
            raise ValueError("No record found to delete.")
        if not allow_multiple and total_count > 1:
            raise ValueError(
                f"Expected exactly one record to delete, found {total_count}."
            )
        logger.debug([col.key for col in cls.__model__.__table__.columns])
        if cls.is_deleted_column in [
            col.key for col in cls.__model__.__table__.columns
        ]:
            update_stmt = (
                update(cls.__model__)
                .filter(*filters)
                .values(is_deleted=True, deleted_at=datetime.now())
            )
            logger.debug(update_stmt)
            await session.execute(update_stmt)
        else:
            delete_stmt = delete(cls.__model__).filter(*filters)
            await session.execute(delete_stmt)

        if commit:
            await session.commit()
