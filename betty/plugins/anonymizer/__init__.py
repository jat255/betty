from typing import List, Tuple, Callable, Set, Type

from betty.ancestry import Ancestry, Person
from betty.functools import walk
from betty.parse import PostParseEvent
from betty.plugin import Plugin
from betty.plugins.privatizer import Privatizer


def anonymize(ancestry: Ancestry) -> None:
    for person in ancestry.people.values():
        if person.private:
            anonymize_person(person)


def anonymize_person(person: Person) -> None:
    person.individual_name = None
    person.family_name = None
    for event in set(person.events):
        event.people.replace([])
    for file in set(person.files):
        file.entities.replace([])
    # If a person is public themselves, or a node connecting other public persons, preserve their place in the graph.
    if person.private and not _has_public_descendants(person):
        person.parents = set()


def _has_public_descendants(person: Person) -> bool:
    for descendant in walk(person, 'children'):
        if not descendant.private:
            return True
    return False


class Anonymizer(Plugin):
    @classmethod
    def comes_after(cls) -> Set[Type]:
        return {Privatizer}

    def subscribes_to(self) -> List[Tuple[str, Callable]]:
        return (
            (PostParseEvent, lambda event: anonymize(event.ancestry)),
        )
