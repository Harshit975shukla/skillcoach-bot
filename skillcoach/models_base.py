from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, max_length=16000)]
Short = Annotated[str, Field(min_length=1, max_length=300)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")
