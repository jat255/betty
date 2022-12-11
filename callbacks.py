from __future__ import annotations

from typing import TypeVar, Callable, Any, Generic, Optional, cast

T = TypeVar('T')
U = TypeVar('U')


class Maybe(Generic[T]):
    def __init__(self, value: Optional[T], _success: bool = True):
        assert _success or value is None
        self._value: Optional[T] = value
        self._success = _success

    @property
    def value(self) -> T:
        if not self._success:
            raise RuntimeError('Maybe not!')
        return cast(T, self._value)

    @property
    def success(self) -> bool:
        return self._success

    def map(self, f: Callable[[T], U]) -> Maybe[U]:
        if not self._success:
            return Maybe(None, False)
        try:
            return Maybe(f(self.value))
        except BaseException:
            return Maybe(None, False)


def int_str(value: int) -> str:
    return str(value)


def str_int(value: str) -> int:
    return int(value)


def int_any(value: int) -> Any:
    return value


def any_str(value: Any) -> str:
    return str(value)


# assertion1: Maybe[int] = Maybe(1)
# reveal_type(assertion1.map)
# assertion2 = assertion1.map(int_str)
# reveal_type(assertion2.map)
# assertion3 = assertion2.map(str_int)
# reveal_type(assertion3.map)
# assertion4 = assertion3.map(str_int)
# reveal_type(assertion4.map)


CallValueT = TypeVar('CallValueT')
CallReturnT = TypeVar('CallReturnT')
FValueT = TypeVar('FValueT')
MapReturnT = TypeVar('MapReturnT')


# @todo Allow Pipeline() to accept an optional args/kwargs processor
# @todo When given, this takes the f value, expands it into args and kwargs, which are then used to call self._f(*args, **kwargs)
# @todo This allow any usage to set the desired function signature.
# @todo This processor must, however, be stored on _Pipeline, because it must be passed on from Pipeline() to _ExtendedPipeline()
# @todo
# @todo HOWEVER: COMMIT ALL CODE FIRST. Then refactor to be able to provide this processor, or not (default is passthrough)
# @todo
# @todo The main benefit of this is composability: Use the pipeline with a processor to accept functions of any signature
# @todo
# @todo We may also need an optional function to determine whether a function has errors. Not all of them (configuration assertions!) raise exceptions!
# @todo Maybe the same processor can do this, which just decorates the actual function calls, so it controls input AND output.
# @todo It can then even decide to use with statements or catch and convert exceptions
# @todo
# @todo

class _Pipeline(Generic[CallValueT, CallReturnT, FValueT]):
    def __init__(self, f: Callable[[FValueT], CallReturnT]):
        self._f = f

    def extend(self, f: Callable[[CallReturnT], MapReturnT]) -> _Pipeline[CallValueT, MapReturnT, CallReturnT]:
        return _ExtendedPipeline(f, self)

    def __or__(self, f: Callable[[CallReturnT], MapReturnT]) -> _Pipeline[CallValueT, MapReturnT, CallReturnT]:
        return self.extend(f)

    def __call__(self, value: CallValueT) -> Maybe[CallReturnT]:
        raise NotImplementedError


class Pipeline(_Pipeline[CallValueT, CallReturnT, CallValueT], Generic[CallValueT, CallReturnT]):
    def __call__(self, value: CallValueT) -> Maybe[CallReturnT]:
        return Maybe(value).map(self._f)


class _ExtendedPipeline(_Pipeline[CallValueT, CallReturnT, FValueT], Generic[CallValueT, CallReturnT, FValueT]):
    def __init__(
            self,
            f: Callable[[FValueT], CallReturnT],
            pipeline: _Pipeline[CallValueT, FValueT, Any],
    ):
        super().__init__(f)
        self._pipeline = pipeline

    def __call__(self, value: CallValueT) -> Maybe[CallReturnT]:
        return self._pipeline(value).map(self._f)


reveal_type(Pipeline(int_str) | str_int | int_str | str_int | int_str)

print(type(Pipeline(int_str)(9).value))
