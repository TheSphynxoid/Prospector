"""The profile as YAML for the advanced editor, with errors that point at a line."""
import yaml
from pydantic import ValidationError

from prospector.profile.model import Profile


class ProfileYamlError(ValueError):
    def __init__(self, line: int | None, message: str):
        super().__init__(f"line {line}: {message}" if line else message)
        self.line, self.message = line, message


def dump(p: Profile) -> str:
    return yaml.safe_dump(p.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=110)


def _line_of(text: str, loc: tuple) -> int | None:
    """The line of the deepest key in `loc` that can be found, following the path down the document."""
    node = yaml.compose(text)
    line = None
    for part in loc:
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                if k.value == str(part):
                    line, node = k.start_mark.line + 1, v
                    break
            else:
                break
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and part < len(node.value):
            node = node.value[part]
            line = node.start_mark.line + 1
        else:
            break
    return line


def load(text: str) -> Profile:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        raise ProfileYamlError(mark.line + 1 if mark else None, getattr(e, "problem", None) or str(e)) from None
    if not isinstance(data, dict):
        raise ProfileYamlError(1, "the profile must be a mapping of keys (skills:, projects:, …)")
    try:
        return Profile.model_validate(data)
    except ValidationError as e:
        err = e.errors(include_input=False)[0]
        loc = tuple(err["loc"])
        where = ".".join(map(str, loc))
        raise ProfileYamlError(_line_of(text, loc), f"{where}: {err['msg']}") from None
