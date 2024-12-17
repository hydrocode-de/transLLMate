from pathlib import Path

from sqlmodel import SQLModel, create_engine, select, Session, func
import pandas as pd

from .models import StructTypeTable, StructTable, Struct, ModuleTable

class Db:
  def __init__(self, path):
    self.path = Path(path).resolve()
    if not self.path.name.endswith('.db'):
      self.path /= 'codebase.db'
    self.engine = create_engine(f"sqlite:///{self.path}")
    if not self.path.exists():
      SQLModel.metadata.create_all(self.engine)
      print('Initialized database.')
    self.session = Session(self.engine)

  @property
  def struct_types(self) -> list[StructTypeTable]:
    return self.session.exec(select(StructTypeTable)).all()

  def add_struct_type(self, name: str, start_token: str, end_token: str):
    t = StructTypeTable(
        name=name,
        start_token=start_token,
        end_token=end_token
    )

    self.session.add(t)
    self.session.commit()
    self.session.refresh(t)
    return t

  def get_structs(self, type: str = None, id: int = None, sig: str = None):
    if id is not None:
      r = self.session.get(StructTable, id)
      if r is None:
        return r
      return Struct.model_validate(r)
    sql = select(StructTable)
    if type is not None:
      sql = sql.join(StructTypeTable).where(func.lower(StructTypeTable.name) == type.lower())
    if sig is not None:
      sql = sql.where(StructTable.signature.ilike(f'%{sig}%'))
    res = self.session.exec(sql).all()
    return [Struct.model_validate(r) for r in res]

  @property
  def structs(self) -> '_STRUCT':
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
      df = pd.DataFrame(columns = ['id', 'path', 'length', 'n_structs'])
    return df.set_index('id')


class _STRUCT:
  def __init__(self, db: Db, type_filter: str = None):
    self._type_filter = type_filter
    self.db = db
    self.__iter_index = 1

  def _struct_model_to_dataframe(self, structs: list[Struct]) -> pd.DataFrame:
    df = pd.DataFrame.from_records([dict(
        id=r.id,
        signature=r.signature,
        body=r.body,
        body_n=r.body_n,
        type=r.type.name,
        end_token=r.type.end_token,
        module=r.module.path
    ) for r in structs])
    if df.empty:
      df = pd.DataFrame(columns=['id', 'signature', 'body', 'body_n', 'type', 'end_token', 'module'])
    return df.set_index('id')

  @property
  def df(self) -> pd.DataFrame:
    structs = self.db.get_structs(type=self._type_filter)
    df = self._struct_model_to_dataframe(structs)
    return df

  def txt(self, item: int | str, mode = 'txt') -> str | list[str]:
    output = []
    df = self.__getitem__(item)
    if df is not None:
      for d in df.to_dict(orient='records'):
        if mode == 'md':
          output.append(f"Original Module: {d['module']}\n```\n{d['signature']}\n{d['body']}\n{d['end_token']}\n```")
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
      raise AttributeError(f"Attribute {name.lower()} is not known and also not a supported Struct: [{', '.join(types)}]")

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
      sql = sql.join(StructTypeTable).where(StructTypeTable.name.ilike(f'%{self._type_filter}%'))

    return self.db.session.exec(sql).one()