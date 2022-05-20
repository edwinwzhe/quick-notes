import os
import yaml
import shutil
import logging
import pathlib
from collections import defaultdict
from typing import Dict, Any, Optional


_logger = logging.getLogger(__name__)


class NoteFormatError(Exception):
    pass


class Config:
    MANDATORY_CONFIG = 'MANDATORY_CONFIG'

    def __init__(self, path: str):
        config_path = pathlib.Path(path).expanduser()
        self._config = self.load_config(config_path)

    def validate_config(self):
        assert 'actions' in self._config
        assert 'note' in self._config
        assert 'app' in self._config
        assert 'search_by' in self._config


    def load_config(self, config_path: pathlib.Path):
        if not config_path.exists():
            dir_path = os.path.dirname(os.path.realpath(__file__))
            shutil.copy(f'{dir_path}/resources/default-config.yaml', config_path)
            _logger.info(f"Default config created at {config_path}")

        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)

        #self.validate_config()
        return cfg

    def get(self, path: str, default: Any = MANDATORY_CONFIG):
        cfg = self._config

        for key in path.split('.'):
            if key in cfg:
                cfg = cfg[key]
            elif default is MANDATORY_CONFIG:
                raise ConfigError(f"Mandatory config {path} is not defined")
            else:
                return default

        return cfg


class Cache:
    def __init__(self, config: Config, path: str, ext: str):
        self._config = config
        self._ext = ext
        self._note_path = pathlib.Path(path).expanduser()
        if not self._note_path.exists():
            self._note_path.mkdir()
            _logger.info("Created directory {note_path} for note keeping")

        self.names = dict()
        self.tags = defaultdict(set)
        self.notes = dict()

        self._cache_notes()

    def get_note_path_for_note_name(self, note_name):
        note_file_ext = self._config.get('note.file_ext')
        note_location = self._config.get('note.location')

        note_file = pathlib.Path("_".join(note_name.lower().split()) + f'.{note_file_ext}')
        note_path = pathlib.Path(note_location).expanduser() / note_file
        return note_path

    @classmethod
    def extract_note_name(cls, note: pathlib.Path):
        with open(note, 'r') as f:
            l = f.readline()

            if not l.strip().startswith('##'):
                raise NoteFormatError("first line does not start with '##'")
            else:
                return l.lstrip('##').strip()

    @classmethod
    def extract_note_tags(cls, note: pathlib.Path):
        with open(note, 'r') as f:
            l = f.readline()
            if not l.strip().startswith('##'):
                raise NoteFormatError("first line does not start with '##'")

            l = f.readline()
            if not l.strip().startswith('#'):  # TODO: use regex for a strict pattern match
                raise NoteFormatError("second line does not start with '#', should be tags. e.g. '#python #101'")

            tags = [t[1:].strip() for t in l.split()]
            return tags

    def uncache_note(self, note: pathlib.Path) -> pathlib.Path:
        if str(note) not in self.notes:
            return

        note_name = self.notes[str(note)]['name']
        tags = self.notes[str(note)]['tags']

        del self.names[note_name]
        for tag in tags:
            self.tags[tag].remove(str(note))

        del self.notes[str(note)]

    def cache_note(self, note: pathlib.Path) -> Optional[pathlib.Path]:
        if not note.exists():
            self.uncache_note(note)
            return
        else:
            note_name = self.extract_note_name(note)
            tags = self.extract_note_tags(note)

            new_note = self.get_note_path_for_note_name(note_name)
            if new_note != note:
                note.rename(new_note)
                self.uncache_note(note)

            self.names[note_name] = str(new_note)

            prev_tags = self.notes.get(str(new_note), {}).get('tags', [])
            for prev_tag in prev_tags:
                if prev_tag not in tags:
                    self.tags[prev_tag].remove(str(new_note))

            for tag in tags:
                self.tags[tag].add(str(new_note))

            self.notes[str(new_note)] = dict(name=note_name, tags=tags)
            return new_note

    def _cache_notes(self):
        for note in self._note_path.glob(f"*.{self._ext}"):
            try:
                self.cache_note(note)
            except NoteFormatError as e:
                _logger.error(f"Failed to load {note}: {e}")