from enum import Enum
from functools import total_ordering
from itertools import chain
from os.path import splitext, basename
from typing import Dict, Optional, List, Iterable, Set, Union, TypeVar, Generic, Callable

from geopy import Point

from betty.locale import Localized, Datey

T = TypeVar('T')


class EventHandlingSetList(Generic[T]):
    def __init__(self, addition_handler: Callable[[T], None], removal_handler: Callable[[T], None]):
        self._values = []
        self._addition_handler = addition_handler
        self._removal_handler = removal_handler

    @property
    def list(self) -> List[T]:
        return list(self._values)

    def prepend(self, *values: T) -> None:
        for value in reversed(values):
            if value in self._values:
                continue
            self._values.insert(0, value)
            self._addition_handler(value)

    def append(self, *values: T) -> None:
        for value in values:
            if value in self._values:
                continue
            self._values.append(value)
            self._addition_handler(value)

    def remove(self, *values: T) -> None:
        for value in values:
            if value not in self._values:
                return
            self._values.remove(value)
            self._removal_handler(value)

    def replace(self, *values: T) -> None:
        self.remove(*list(self._values))
        self.append(*values)

    def clear(self) -> None:
        self.replace()

    def __iter__(self):
        return self._values.__iter__()

    def __len__(self):
        return len(self._values)

    def __getitem__(self, item):
        return self._values[item]


ManyAssociation = Union[EventHandlingSetList[T], Iterable]


class _to_many:
    def __init__(self, self_name: str, associated_name: str):
        self._self_name = self_name
        self._associated_name = associated_name

    def __call__(self, cls):
        _decorated_self_name = '_%s' % self._self_name
        original_init = cls.__init__

        def _init(decorated_self, *args, **kwargs):
            association = EventHandlingSetList(self._create_addition_handler(decorated_self),
                                               self._create_removal_handler(decorated_self))
            setattr(decorated_self, _decorated_self_name, association)
            original_init(decorated_self, *args, **kwargs)
        cls.__init__ = _init
        setattr(cls, self._self_name, property(
            lambda decorated_self: getattr(decorated_self, _decorated_self_name),
            lambda decorated_self, values: getattr(decorated_self, _decorated_self_name).replace(*values),
            lambda decorated_self: getattr(decorated_self, _decorated_self_name).clear(),
        ))
        return cls

    def _create_addition_handler(self, decorated_self):
        raise NotImplementedError

    def _create_removal_handler(self, decorated_self):
        raise NotImplementedError


class many_to_many(_to_many):
    def _create_addition_handler(self, decorated_self):
        return lambda associated: getattr(associated, self._associated_name).append(decorated_self)

    def _create_removal_handler(self, decorated_self):
        return lambda associated: getattr(associated, self._associated_name).remove(decorated_self)


def bridged_many_to_many(left_associated_name: str, left_self_name: str, right_self_name: str, right_associated_name: str):
    def decorator(cls):
        cls = many_to_one(left_self_name, left_associated_name, lambda decorated_self: delattr(decorated_self, right_self_name))(cls)
        cls = many_to_one(right_self_name, right_associated_name, lambda decorated_self: delattr(decorated_self, left_self_name))(cls)
        return cls
    return decorator


class one_to_many(_to_many):
    def _create_addition_handler(self, decorated_self):
        return lambda associated: setattr(associated, self._associated_name, decorated_self)

    def _create_removal_handler(self, decorated_self):
        return lambda associated: setattr(associated, self._associated_name, None)


def many_to_one(self_name: str, associated_name: str, _removal_handler: Optional[Callable[[T], None]] = None):
    def decorator(cls):
        _decorated_self_name = '_%s' % self_name
        original_init = cls.__init__

        def _init(decorated_self, *args, **kwargs):
            association = None
            setattr(decorated_self, _decorated_self_name, association)
            original_init(decorated_self, *args, **kwargs)
        cls.__init__ = _init

        def _set(decorated_self, value):
            previous_value = getattr(decorated_self, _decorated_self_name)
            if previous_value == value:
                return
            setattr(decorated_self, _decorated_self_name, value)
            if previous_value is not None:
                getattr(previous_value, associated_name).remove(decorated_self)
                if value is None and _removal_handler is not None:
                    _removal_handler(decorated_self)
            if value is not None:
                getattr(value, associated_name).append(decorated_self)
        setattr(cls, self_name, property(
            lambda decorated_self: getattr(decorated_self, _decorated_self_name),
            _set,
            lambda decorated_self: _set(decorated_self, None),
        ))
        return cls
    return decorator


class Resource:
    @property
    def resource_type_name(self) -> str:
        raise NotImplementedError


class HasPrivacy:
    private: Optional[bool]

    def __init__(self):
        self.private = None


class Dated:
    date: Optional[Datey]

    def __init__(self):
        self.date = None


class Note:
    def __init__(self, text: str):
        self._text = text

    @property
    def text(self):
        return self._text


class Identifiable:
    def __init__(self, id: str):
        self._id = id

    @property
    def id(self) -> str:
        return self._id


class Described:
    def __init__(self):
        self._description = None

    @property
    def description(self) -> Optional[str]:
        return self._description

    @description.setter
    def description(self, description: str):
        self._description = description


class HasMediaType:
    def __init__(self):
        self._media_type = None

    @property
    def media_type(self) -> Optional[str]:
        return self._media_type

    @media_type.setter
    def media_type(self, media_type: str):
        self._media_type = media_type


class Link(HasMediaType, Localized, Described):
    url: str

    def __init__(self, url: str):
        HasMediaType.__init__(self)
        Localized.__init__(self)
        Described.__init__(self)
        self.url = url
        self._label = None
        self._relationship = None

    @property
    def relationship(self) -> Optional[str]:
        return self._relationship

    @relationship.setter
    def relationship(self, relationship: str) -> None:
        self._relationship = relationship

    @property
    def label(self) -> Optional[str]:
        return self._label

    @label.setter
    def label(self, label: str) -> None:
        self._label = label


class HasLinks:
    def __init__(self):
        self._links = set()

    @property
    def links(self) -> Set[Link]:
        return self._links


@many_to_many('resources', 'files')
class File(Resource, Identifiable, Described, HasPrivacy, HasMediaType):
    resource_type_name = 'file'
    resources: ManyAssociation[Resource]
    notes: List[Note]

    def __init__(self, file_id: str, path: str):
        Identifiable.__init__(self, file_id)
        Described.__init__(self)
        HasPrivacy.__init__(self)
        HasMediaType.__init__(self)
        self._path = path
        self.notes = []

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return basename(self._path)

    @property
    def basename(self) -> str:
        return splitext(self._path)[0]

    @property
    def extension(self) -> Optional[str]:
        extension = splitext(self._path)[1][1:]
        return extension if extension else None

    @property
    def sources(self) -> Iterable['Source']:
        for entity in self.resources:
            if isinstance(entity, Source):
                yield entity
            if isinstance(entity, Citation):
                yield entity.source

    @property
    def citations(self) -> Iterable['Citation']:
        for entity in self.resources:
            if isinstance(entity, Citation):
                yield entity


@many_to_many('files', 'resources')
class HasFiles:
    files: ManyAssociation[File]


@many_to_one('contained_by', 'contains')
@one_to_many('contains', 'contained_by')
@one_to_many('citations', 'source')
class Source(Resource, Dated, HasFiles, HasLinks, HasPrivacy):
    resource_type_name = 'source'
    name: str
    contained_by: 'Source'
    contains: ManyAssociation['Source']
    citations: ManyAssociation['Citation']

    def __init__(self, name: Optional[str] = None):
        Dated.__init__(self)
        HasFiles.__init__(self)
        HasLinks.__init__(self)
        HasPrivacy.__init__(self)
        if name is not None:
            self.name = name
        self._author = None
        self._publisher = None

    @property
    def author(self) -> Optional[str]:
        return self._author

    @author.setter
    def author(self, author: str):
        self._author = author

    @property
    def publisher(self) -> Optional[str]:
        return self._publisher

    @publisher.setter
    def publisher(self, publisher: str):
        self._publisher = publisher


class IdentifiableSource(Source, Identifiable):
    def __init__(self, source_id: str, *args, **kwargs):
        Identifiable.__init__(self, source_id)
        Source.__init__(self, *args, **kwargs)


@many_to_many('facts', 'citations')
@many_to_one('source', 'citations')
class Citation(Resource, Dated, HasFiles, HasPrivacy):
    resource_type_name = 'citation'
    facts: ManyAssociation[Resource]
    source: Source

    def __init__(self, source: Source):
        Dated.__init__(self)
        HasFiles.__init__(self)
        HasPrivacy.__init__(self)
        self._location = None
        self.source = source

    @property
    def location(self) -> Optional[str]:
        return self._location

    @location.setter
    def location(self, location: str):
        self._location = location


class IdentifiableCitation(Citation, Identifiable):
    def __init__(self, citation_id: str, *args, **kwargs):
        Identifiable.__init__(self, citation_id)
        Citation.__init__(self, *args, **kwargs)


@many_to_many('citations', 'facts')
class HasCitations:
    citations: ManyAssociation[Citation]


class LocalizedName(Localized):
    def __init__(self, name: str, locale: Optional[str] = None):
        Localized.__init__(self)
        self._name = name
        self.locale = locale

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._name == other._name and self.locale == other.locale

    def __repr__(self):
        return '%s(%s, %s)' % (type(self).__name__, self._name, self.locale.__repr__())

    def __str__(self):
        return self._name

    @property
    def name(self) -> str:
        return self._name


@one_to_many('events', 'place')
@many_to_one('enclosed_by', 'encloses')
@one_to_many('encloses', 'enclosed_by')
class Place(Resource, Identifiable, HasLinks):
    resource_type_name = 'place'

    def __init__(self, place_id: str, names: List[LocalizedName]):
        Identifiable.__init__(self, place_id)
        HasLinks.__init__(self)
        self._names = names
        self._coordinates = None

    @property
    def names(self) -> List[LocalizedName]:
        return self._names

    @property
    def coordinates(self) -> Optional[Point]:
        return self._coordinates

    @coordinates.setter
    def coordinates(self, coordinates: Point):
        self._coordinates = coordinates


@bridged_many_to_many('presences', 'person', 'event', 'presences')
class Presence:
    person: Optional['Person']
    event: Optional['Event']
    role: 'Presence.Role'

    class Role(Enum):
        SUBJECT = 'subject'
        WITNESS = 'witness'
        ATTENDEE = 'attendee'

    def __init__(self, person: 'Person', role: Role, event: 'Event'):
        self.person = person
        self.role = role
        self.event = event


@many_to_one('place', 'events')
@one_to_many('presences', 'event')
class Event(Resource, Dated, HasFiles, HasCitations, Described, HasPrivacy):
    resource_type_name = 'event'
    place: Place
    presences: ManyAssociation[Presence]

    class Type(Enum):
        BIRTH = 'birth'
        BAPTISM = 'baptism'
        ADOPTION = 'adoption'
        CREMATION = 'cremation'
        DEATH = 'death'
        BURIAL = 'burial'
        ENGAGEMENT = 'engagement'
        MARRIAGE = 'marriage'
        MARRIAGE_BANNS = 'marriage-banns'
        DIVORCE = 'divorce'
        DIVORCE_FILING = 'divorce-filing'
        RESIDENCE = 'residence'
        IMMIGRATION = 'immigration'
        EMIGRATION = 'emigration'
        OCCUPATION = 'occupation'
        RETIREMENT = 'retirement'

    def __init__(self, event_type: Type, date: Optional[Datey] = None):
        Dated.__init__(self)
        HasFiles.__init__(self)
        HasCitations.__init__(self)
        Described.__init__(self)
        HasPrivacy.__init__(self)
        self.date = date
        self._type = event_type

    @property
    def type(self):
        return self._type


class IdentifiableEvent(Event, Identifiable):
    def __init__(self, event_id: str, *args, **kwargs):
        Identifiable.__init__(self, event_id)
        Event.__init__(self, *args, **kwargs)


@total_ordering
@many_to_one('person', 'names')
class PersonName(Localized, HasCitations):
    person: Optional['Person']

    def __init__(self, individual: Optional[str] = None, affiliation: Optional[str] = None):
        Localized.__init__(self)
        HasCitations.__init__(self)
        self._individual = individual
        self._affiliation = affiliation

    def __eq__(self, other):
        if other is None:
            return False
        if not isinstance(other, PersonName):
            return NotImplemented
        return (self._affiliation or '', self._individual or '') == (other._affiliation or '', other._individual or '')

    def __gt__(self, other):
        if other is None:
            return True
        if not isinstance(other, PersonName):
            return NotImplemented
        return (self._affiliation or '', self._individual or '') > (other._affiliation or '', other._individual or '')

    @property
    def individual(self) -> str:
        return self._individual

    @property
    def affiliation(self) -> str:
        return self._affiliation


@total_ordering
@many_to_many('parents', 'children')
@many_to_many('children', 'parents')
@one_to_many('presences', 'person')
@one_to_many('names', 'person')
class Person(Resource, Identifiable, HasFiles, HasCitations, HasLinks, HasPrivacy):
    resource_type_name = 'person'
    parents: ManyAssociation['Person']
    children: ManyAssociation['Person']
    presences: ManyAssociation[Presence]
    names: ManyAssociation[PersonName]

    def __init__(self, person_id: str):
        Identifiable.__init__(self, person_id)
        HasFiles.__init__(self)
        HasCitations.__init__(self)
        HasLinks.__init__(self)
        HasPrivacy.__init__(self)

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.id == other.id

    def __gt__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.id > other.id

    @property
    def name(self) -> Optional[PersonName]:
        try:
            return self._names.list[0]
        except IndexError:
            return None

    @property
    def alternative_names(self) -> List[PersonName]:
        return self._names.list[1:]

    @property
    def start(self) -> Optional[Event]:
        for event_type in [Event.Type.BIRTH, Event.Type.BAPTISM]:
            for presence in self.presences:
                if presence.event.type == event_type and presence.role == Presence.Role.SUBJECT:
                    return presence.event
        return None

    @property
    def end(self) -> Optional[Event]:
        for event_type in [Event.Type.DEATH, Event.Type.BURIAL]:
            for presence in self.presences:
                if presence.event.type == event_type and presence.role == Presence.Role.SUBJECT:
                    return presence.event
        return None

    @property
    def siblings(self) -> List:
        siblings = []
        for parent in self._parents:
            for sibling in parent.children:
                if sibling != self and sibling not in siblings:
                    siblings.append(sibling)
        return siblings


class Ancestry:
    files: Dict[str, File]
    people: Dict[str, Person]
    places: Dict[str, Place]
    events: Dict[str, IdentifiableEvent]
    sources: Dict[str, IdentifiableSource]
    citations: Dict[str, IdentifiableCitation]

    def __init__(self):
        self.files = {}
        self.people = {}
        self.places = {}
        self.events = {}
        self.sources = {}
        self.citations = {}

    @property
    def resources(self) -> Iterable[Resource]:
        return chain(
            self.files.values(),
            self.people.values(),
            self.places.values(),
            self.events.values(),
            self.sources.values(),
            self.citations.values(),
        )
