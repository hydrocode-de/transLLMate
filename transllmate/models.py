from sqlmodel import SQLModel, Field, Relationship


class StructTypeBase(SQLModel):
    name: str
    start_token: str
    end_token: str


class StructTypeTable(StructTypeBase, table=True):
    __tablename__ = "struct_types"
    id: int | None = Field(default=None, primary_key=True)
    structs: list["StructTable"] = Relationship(back_populates="type")


class StructBase(SQLModel):
    signature: str | None = None
    body: str | None = Field(default=None, repr=False)
    body_n: int | None = None


class StructTable(StructBase, table=True):
    __tablename__ = "structs"
    id: int | None = Field(default=None, primary_key=True)
    type_id: int = Field(foreign_key="struct_types.id")
    module_id: int = Field(foreign_key="modules.id")

    type: "StructTypeTable" = Relationship(back_populates="structs")
    module: "ModuleTable" = Relationship(back_populates="structs")
    translations: list["TranslateTable"] = Relationship(back_populates="struct")


class ModuleBase(SQLModel):
    path: str
    length: int
    n_structs: int


class ModuleTable(ModuleBase, table=True):
    __tablename__ = "modules"
    id: int | None = Field(default=None, primary_key=True)
    structs: list[StructTable] = Relationship(back_populates="module")


class Struct(StructBase):
    id: int
    module: ModuleBase
    type: StructTypeBase


class Module(ModuleBase):
    structs: list[Struct]


class TranslateBase(SQLModel):
    model: str
    context: int
    temperature: float
    body: str


class TranslateTable(TranslateBase, table=True):
    __tablename__ = "translations"
    id: int | None = Field(default=None, primary_key=True)
    struct_id: int = Field(foreign_key="structs.id")
    struct: StructTable = Relationship(back_populates="translations")

class TranslateWithStruct(TranslateBase):
    body: str
    struct: Struct

class StructWithTranslation(StructBase):
    id: int
    module: ModuleBase
    type: StructTypeBase
    structs: list[TranslateBase] = []
