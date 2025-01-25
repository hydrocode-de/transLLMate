#translator.py
from pathlib import Path
import tempfile
import subprocess

from pydantic import BaseModel, field_validator, Field

from transllmate.db import Db
from transllmate.models import TranslateWithStruct


class Translator(BaseModel):
    db: Db | str
    fabric_path: str | None = None
    
    fabric_cmd: str = 'docker compose run --rm -T fabric'
    model: str = 'qwen2.5-coder:14b'
    pattern: str = 'vba_translate'
    context_length: int = 6000
    temperature: float = Field(default=0.6, le=1.0, ge=0.0)
    stream: bool = False

    _history: list[str] = []
    
    @field_validator('db', mode='before')
    def validate_db(cls, val):
        if isinstance(val, str):
            return Db(path=val)
        return val
    
    def model_post_init(self, __context):
        # set the fabric path
        if self.fabric_path is None:
            p = Path('~').expanduser() / 'localai'
            if not p.exists():
                raise AttributeError('Please provide the path to fabric as `fabric_path`')
            self.fabric_path = p
    
    @property
    def opts(self):
        return f"-p {self.pattern} -m {self.model} -t {self.temperature} --modelContextLength={self.context_length}"
    
    def translate(self, id: int, suffix: str = '.txt', stream: bool = False):
        # write the original struct to a temporary file
        with tempfile.NamedTemporaryFile(mode='r+', suffix=suffix) as f:
            f.write(self.db.structs.txt(id, mode='txt'))
            f.seek(0)

            # build the command
            cmd = f"cd {self.fabric_path} && cat {f.name} | {self.fabric_cmd} {self.opts}"
            if stream:
                cmd += " --stream"
            self._history.append(cmd)
            
            # run
            res = subprocess.run(cmd, shell=True, capture_output=not stream)
            if not stream:
                return res.stdout.decode()
    
    def has_id(self, id: int):
        return self.db.has_translation(
            struct=id,
            model=self.model, 
            context=self.context_length, 
            temperature=self.temperature
        )
    
    def save_translation(self, id: int, body: str):
        self.db.add_translation(
            struct=id,
            model=self.model,
            context=self.context_length,
            temperature=self.temperature,
            body=body
        )
    
    @property
    def translations(self) -> '_TRANSLATION':
        return _TRANSLATION(self)


class _TRANSLATION:
    def __init__(self, translator: Translator):
        self.translator = translator
    
    def all(self) -> list[TranslateWithStruct]:
        translations = self.translator.db.get_translations(
            model=self.translator.model,
            context=self.translator.context_length,
            temperature=self.translator.temperature
        )

        return [TranslateWithStruct.model_validate(t) for t in translations]
