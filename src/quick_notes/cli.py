import logging
import os
import glob
import pathlib
import subprocess
from collections import defaultdict

from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion

from .utils import Config, Cache, NoteFormatError


_logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "~/quick-notes.yaml"
ACTION_CREATE_CODE = "c"
ACTION_CREATE_NAME = 'create'
ACTION_DELETE_NAME = 'delete'
ACTION_RESTORE_NAME = 'restore'
ACTION_QUIT_CODE = "q"


class QuickNoteCompleter(Completer):
    def __init__(self, config, cache):
        self._config = config
        self._cache = cache

        self._actions = self._config.get('actions')
        self._search_by = self._config.get('search_by')

    def _get_action_hint(self, action):
        if action in self._actions:
            hint = self._actions[action]['hint']
        else:
            action_keys = list(self._actions.keys())
            action_names = [v['name'] for v in self._actions.values()]
            action_options = [f"{name}({key})" for name, key in zip(action_names, action_keys)]
            hint = f"action '{action}' undefined, should be one of {', '.join(action_options)}"

        return hint

    def _get_search_by_hint(self, search_by):
        if search_by in self._search_by:
            hint = self._search_by[search_by]['hint']
        else:
            search_by_keys = list(self._search_by.keys())
            search_by_names = [v['name'] for v in self._search_by.values()]
            search_by_options = [f"{name}({key})" for name, key in zip(search_by_names, search_by_keys)]

            hint = f"search by '{search_by}' undefined, should be one of {', '.join(search_by_options)}"

        return hint

    def _completion_generator(self, document):
        user_input = document.text.lstrip()

        if len(user_input) == 1:
            action = user_input[0]

            if action == ACTION_CREATE_CODE:
                yield Completion(
                    text=ACTION_CREATE_NAME,
                    start_position=-len(document.text_before_cursor),
                    display="create note (press enter)",
                )
            else:
                hint = self._get_action_hint(action)

                yield Completion(
                    text='',
                    start_position=-len(document.text_before_cursor),
                    display=hint,
                )
        elif len(user_input) == 2:
            action = user_input[0]
            search_by = user_input[1]

            hint = self._get_action_hint(action) + ', '
            hint += self._get_search_by_hint(search_by)

            yield Completion(
                text='',
                start_position=-len(document.text_before_cursor),
                display=hint,
                #     display_meta=tags,
            )
        elif len(user_input) > 2:
            action = user_input[0]
            search_by = user_input[1]
            keywords = user_input[3:]

            if action in self._actions:
                action_name = self._actions[action]['name']
            else:
                return

            if search_by == 't':
                if keywords.strip():
                    search_tags = keywords.split(',')

                    tags = [tag for tag in self._cache.tags.keys() if any(t for t in search_tags if t in tag)]
                    for t in sorted(tags):
                        for note in self._cache.tags[t]:
                            yield Completion(
                                text=action_name + ' ' + note,
                                start_position=-len(document.text_before_cursor),
                                display=self._cache.notes[note]['name'],
                                display_meta='#' + t,
                            )
                else:
                    for tag in sorted(self._cache.tags.keys()):
                        yield Completion(
                            text=' ',
                            start_position=-len(document.text_before_cursor),
                            display=f"#{tag} ({len(self._cache.tags[tag])} notes)",
                        )
            elif search_by == 'n':
                if keywords.strip():
                    names = [h for h in self._cache.names.keys() if keywords.lower() in h.lower()]
                else:
                    names = [h for h in self._cache.names.keys()]

                for name in names:
                    note = self._cache.names[name]
                    tags = self._cache.notes[note]['tags']
                    tags = '#' + ' #'.join(tags) if tags else ''

                    yield Completion(
                        text=action_name + ' ' + self._cache.names[name],
                        start_position=-len(document.text_before_cursor),
                        display=name,
                        display_meta=tags,
                    )
            elif search_by == 'c' and len(keywords.strip()) >= 2:
                p = subprocess.Popen(
                    [f"grep -in '{keywords}' {self._config.get('note.location')}/*.md"],
                    shell=True,
                    stdout=subprocess.PIPE,
                )

                for line in p.stdout:
                    note_path, match = line.decode('UTF-8').split(':', 1)
                    note_name = self._cache.notes[note_path]['name']

                    yield Completion(
                        text=action_name + ' ' + note_path,
                        start_position=-len(document.text_before_cursor),
                        display=note_name,
                        display_meta=match.strip(),
                    )

    def get_completions(self, document, complete_event):
        yield from self._completion_generator(document)


def create_note(config: Config, cache: Cache, operation: str):
    executor = config.get(f'actions.{ACTION_CREATE_CODE}.executor')
    tmp_file_path = config.get("note.tmp_file_path")

    if operation in (ACTION_CREATE_CODE, ACTION_CREATE_NAME):
        # create note without name
        note = pathlib.Path(tmp_file_path)
    else:
        assert operation.startswith(ACTION_CREATE_NAME)
        note_name = operation.lstrip(ACTION_CREATE_NAME).strip().title()
        note = cache.get_note_path_for_note_name(note_name)

        if note.exists():
            print("Aborted creating note, already exist: {note_file}")
            return

        with open(note, 'w') as f:
            f.write(note_name + '\n\n#tag')

    os.system(f"{executor} {note}")

    try:
        cached_note = cache.cache_note(note)
    except NoteFormatError as e:
        print(f"Failed to cache {note}: {e}")
        return

    print(f"Created note cached as {cached_note}")


def delete_note(config: Config, cache: Cache, operation: str):
    note = pathlib.Path(operation.split()[-1])
    deleted_dir = pathlib.Path(config.get('note.location')).expanduser() / pathlib.Path('deleted')
    deleted_note = deleted_dir / pathlib.Path(note.name)

    if not deleted_dir.exists():
        deleted_dir.mkdir()

    note.rename(deleted_note)
    cache.cache_note(note)
    print(f"Marked {note} deleted")


def restore_note(config: Config, cache: Cache, operation: str):
    deleted_note = pathlib.Path(operation.split()[-1])
    restored_note = pathlib.Path(config.get('note.location')).expanduser() / pathlib.Path(deleted_note.name)

    deleted_note.rename(restored_note)
    cache.cache_note(restored_note)
    print(f"Restored {restored_note}")


def operate_note(config: Config, cache: Cache, operation: str):
    action_name, note_path = operation.split()

    executor = [action_config['executor']
                for _, action_config in config.get('actions').items()
                if action_config['name'] == action_name][0]

    os.system(f"{executor} {note_path}")
    cache.cache_note(pathlib.Path(note_path))


def handle_operation(config: Config, cache: Cache, operation: str):
    if not operation:
        return

    if operation == ACTION_CREATE_CODE or operation.startswith(ACTION_CREATE_NAME):
        create_note(config, cache, operation)
    elif operation == ACTION_QUIT_CODE:
        raise KeyboardInterrupt()
    elif operation.split()[0] == ACTION_DELETE_NAME:
        delete_note(config, cache, operation)
    elif operation.split()[0] == ACTION_RESTORE_NAME:
        restore_note(config, cache, operation)
    else:
        operate_note(config, cache, operation)

def cli(debug: bool = True):
    logging.basicConfig(level='INFO')

    if debug:
        dir_path = os.path.dirname(os.path.realpath(__file__))
        config_path = f'{dir_path}/resources/default-config.yaml'
    else:
        config_path = DEFAULT_CONFIG_PATH

    config = Config(config_path)
    cache = Cache(config=config, path=config.get('note.location'), ext=config.get('note.file_ext'))

    completer = QuickNoteCompleter(config, cache)
    while True:
        prompt_str = config.get('app.prompt', 'quick-note> ')

        try:
            operation = prompt(prompt_str, completer=completer).strip()
            handle_operation(config, cache, operation)
        except KeyboardInterrupt as e:
            print("quick-notes terminated")
            break