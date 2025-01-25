from typing import Annotated, Any
from pathlib import Path

from pydantic import BaseModel, field_validator, Field
from sqlmodel import SQLModel, create_engine, select, Session, func
import pandas as pd

from .models import StructTypeTable, StructTable, Struct, ModuleTable, TranslateTable


class Db(BaseModel):
    path: Path = Field(kw_only=False)
    session: Annotated[Any, Session] = Field(default=None)

    @field_validator('path')
    def validate_path(cls, val):
        path = Path(val).resolve()
        if not path.name.endswith('.db'):
            path /= "codebase.db"
        return path
    
    def model_post_init(self, __context):
        # build the engine and create the database if needed
        engine = create_engine(f"sqlite:///{self.path}")
        if not self.path.exists():
            SQLModel.metadata.create_all(engine)
        self.session = Session(engine)

    @property
    def struct_types(self) -> list[StructTypeTable]:
        return self.session.exec(select(StructTypeTable)).all()

    def add_struct_type(self, name: str, start_token: str, end_token: str):
        t = StructTypeTable(name=name, start_token=start_token, end_token=end_token)

        self.session.add(t)
        self.session.commit()
        self.session.refresh(t)
        return t
    
    def add_translation(self, struct: StructTable | int, model: str, context: int, temperature: float, body: str):
        if isinstance(struct, StructTable):
            struct_id = struct.id
        else: 
            struct_id = struct

        # create the object
        t = TranslateTable(
            struct_id=struct_id,
            model=model,
            context=context,
            temperature=temperature,
            body=body
        )

        self.session.add(t)
        self.session.commit()
        self.session.refresh(t)
        return t
    
    def has_translation(self, struct: StructTable | int, model: str = None, context: int = None, temperature: float = None):
        if isinstance(struct, StructTable):
            struct = id
        sql = select(func.count(TranslateTable.id)).where(TranslateTable.struct_id==struct)
        if model is not None:
            sql = sql.where(TranslateTable.model==model)
        if context is not None:
            sql = sql.where(TranslateTable.context==context)
        if temperature is not None:
            sql = sql.where(TranslateTable.temperature==temperature)
        
        return self.session.exec(sql).one() > 0
    
    def get_translations(self, id: int = None, model: str = None, context: int = None, temperature: float = None) -> list[TranslateTable]:
        if id is not None:
            return self.session.get(TranslateTable, id)
        sql = select(TranslateTable)
        if model is not None:
            sql = sql.where(TranslateTable.model==model)
        if context is not None:
            sql = sql.where(TranslateTable.context==context)
        if temperature is not None:
            sql = sql.where(TranslateTable.temperature==temperature)
        
        return self.session.exec(sql).all()

    def get_structs(self, type: str = None, id: int = None, sig: str = None):
        if id is not None:
            r = self.session.get(StructTable, id)
            if r is None:
                return r
            return Struct.model_validate(r)
        sql = select(StructTable)
        if type is not None:
            sql = sql.join(StructTypeTable).where(
                func.lower(StructTypeTable.name) == type.lower()
            )
        if sig is not None:
            sql = sql.where(StructTable.signature.ilike(f"%{sig}%"))
        res = self.session.exec(sql).all()
        return [Struct.model_validate(r) for r in res]

    @property
    def structs(self) -> "_STRUCT":
        return _STRUCT(self)

    def add_module(self, module: ModuleTable):
        self.session.add(module)
        self.session.commit()
        self.session.refresh(module)
        return module

    def get_modules(self):
        return self.session.exec(select(ModuleTable)).all()

    @property
    def modules(self):
        df = pd.DataFrame.from_records([m.model_dump() for m in self.get_modules()])
        if df.empty:
            df = pd.DataFrame(columns=["id", "path", "length", "n_structs"])
        return df.set_index("id")


class _STRUCT:
    def __init__(self, db: Db, type_filter: str = None):
        self._type_filter = type_filter
        self.db = db
        self.__iter_index = 1

    def _struct_model_to_dataframe(self, structs: list[Struct]) -> pd.DataFrame:
        df = pd.DataFrame.from_records(
            [
                dict(
                    id=r.id,
                    signature=r.signature,
                    body=r.body,
                    body_n=r.body_n,
                    type=r.type.name,
                    end_token=r.type.end_token,
                    module=r.module.path,
                )
                for r in structs
            ]
        )
        if df.empty:
            df = pd.DataFrame(
                columns=[
                    "id",
                    "signature",
                    "body",
                    "body_n",
                    "type",
                    "end_token",
                    "module",
                ]
            )
        return df.set_index("id")

    @property
    def df(self) -> pd.DataFrame:
        structs = self.db.get_structs(type=self._type_filter)
        df = self._struct_model_to_dataframe(structs)
        return df

    def txt(self, item: int | str, mode="txt") -> str | list[str]:
        output = []
        df = self.__getitem__(item)
        if df is not None:
            for d in df.to_dict(orient="records"):
                if mode == "md":
                    output.append(
                        f"Original Module: {d['module']}\n```\n{d['signature']}\n{d['body']}\n{d['end_token']}\n```"
                    )
                else:
                    output.append(f"{d['signature']}\n{d['body']}\n{d['end_token']}")

        if len(output) == 1:
            return output[0]
        else:
            return output

    def __getattr__(self, name: str):
        types = [t.name.lower() for t in self.db.struct_types]
        if name.lower() in types:
            return _STRUCT(self.db, type_filter=name)
        else:
            raise AttributeError(
                f"Attribute {name.lower()} is not known and also not a supported Struct: [{', '.join(types)}]"
            )

    def __getitem__(self, key: int | str):
        if isinstance(key, int):
            struct = self.db.get_structs(id=key)
            if struct is None:
                return None
            return self._struct_model_to_dataframe([struct])
        elif isinstance(key, str):
            structs = self.db.get_structs(sig=key, type=self._type_filter)
            df = self._struct_model_to_dataframe(structs)
            return df
        else:
            return super().__getitem__(key)

    def __len__(self):
        sql = select(func.count(StructTable.id))
        if self._type_filter is not None:
            sql = sql.join(StructTypeTable).where(
                StructTypeTable.name.ilike(f"%{self._type_filter}%")
            )

        return self.db.session.exec(sql).one()
