'''
Typeform data
'''

REQUIRES = [
    # TODO Add
]

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Iterable

from .core import Paths, get_files

# TODO Fix
from my.config import eightsleep as user_config

@dataclass
class typeform(user_config):
    # paths[s]/glob to the exported JSON data
    export_path: Paths


def inputs() -> Sequence[Path]:
    return get_files(typeform.export_path)


import typeform.dal as dal


def responses():
    _dal = dal.DAL(inputs())
    yield from _dal.responses()

def answers():
    _dal = dal.DAL(inputs())
    yield from _dal.answers()

def forms():
    _dal = dal.DAL(inputs())
    yield from _dal.forms()
