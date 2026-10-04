"""Validated, versioned public machine catalogs and private rotor settings."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,:?'/-()\"=+@"


def _object(value: Any, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(fields))}")
    return value


def _indices(value: Any, count: int | None, label: str) -> tuple[int, ...]:
    if not isinstance(value, list) or (count is not None and len(value) != count):
        raise ValueError(f"{label} must be a list" + (f" of {count} indices" if count is not None else ""))
    if any(type(v) is not int or not 0 <= v < len(ALPHABET) for v in value):
        raise ValueError(f"{label} indices must be integers from 0 to 48")
    return tuple(value)


def _permutation(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != len(ALPHABET) or set(value) != set(ALPHABET):
        raise ValueError(f"{label} must be a permutation of the 49-character alphabet")
    return value


@dataclass(frozen=True)
class RotorSpec:
    wiring: str
    notches: tuple[int, ...]


@dataclass(frozen=True)
class Machine:
    alphabet: str
    rotors: dict[str, RotorSpec]
    reflector: str

    @classmethod
    def from_dict(cls, value: dict) -> Machine:
        _object(value, {"version", "alphabet", "rotors", "reflector"}, "machine")
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("unsupported machine version")
        if value["alphabet"] != ALPHABET:
            raise ValueError("machine alphabet must match the protocol alphabet exactly")
        catalog = value["rotors"]
        if not isinstance(catalog, dict) or not 3 <= len(catalog) <= 256:
            raise ValueError("machine requires 3 to 256 named rotors")
        rotors = {}
        for name, spec in catalog.items():
            if not isinstance(name, str) or not name.isascii() or not name or len(name) > 64:
                raise ValueError("rotor names must be 1 to 64 ASCII characters")
            _object(spec, {"wiring", "notches"}, f"rotor {name}")
            wiring = _permutation(spec["wiring"], f"rotor {name} wiring")
            notches = _indices(spec["notches"], None, f"rotor {name} notches")
            if not notches or len(set(notches)) != len(notches):
                raise ValueError("rotor notches must be nonempty and unique")
            rotors[name] = RotorSpec(wiring, notches)
        reflector = _permutation(value["reflector"], "reflector")
        if any(reflector[ALPHABET.index(reflector[i])] != ch for i, ch in enumerate(ALPHABET)):
            raise ValueError("reflector must be reciprocal")
        if sum(a == b for a, b in zip(ALPHABET, reflector)) != 1:
            raise ValueError("reflector must contain exactly one fixed point")
        return cls(ALPHABET, rotors, reflector)

    def to_dict(self) -> dict:
        return {"version": 1, "alphabet": self.alphabet, "rotors": {
            name: {"wiring": rotor.wiring, "notches": list(rotor.notches)}
            for name, rotor in self.rotors.items()}, "reflector": self.reflector}

    @property
    def fingerprint(self) -> bytes:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("ascii")).digest()[:8]


@dataclass(frozen=True)
class Key:
    rotors: tuple[str, ...]
    positions: tuple[int, ...]
    rings: tuple[int, ...]
    plugboard: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: dict, machine: Machine) -> Key:
        _object(value, {"version", "rotors", "positions", "rings", "plugboard"}, "key")
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("unsupported key version")
        rotors = value["rotors"]
        if not isinstance(rotors, list) or not 3 <= len(rotors) <= 8:
            raise ValueError("select 3 to 8 distinct rotors")
        if any(not isinstance(name, str) or name not in machine.rotors for name in rotors):
            raise ValueError("key references an unknown rotor")
        if len(set(rotors)) != len(rotors):
            raise ValueError("selected rotors must be distinct")
        positions = _indices(value["positions"], len(rotors), "positions")
        rings = _indices(value["rings"], len(rotors), "rings")
        plugs = value["plugboard"]
        if not isinstance(plugs, list) or not 10 <= len(plugs) <= 16:
            raise ValueError("plugboard requires 10 to 16 disjoint pairs")
        if any(not isinstance(pair, str) or len(pair) != 2 or any(c not in ALPHABET for c in pair) for pair in plugs):
            raise ValueError("each plugboard pair must contain two alphabet characters")
        flat = "".join(plugs)
        if len(set(flat)) != len(flat):
            raise ValueError("plugboard pairs must be disjoint, without self-pairs")
        return cls(tuple(rotors), positions, rings, tuple(plugs))

    def to_dict(self) -> dict:
        return {"version": 1, "rotors": list(self.rotors), "positions": list(self.positions),
                "rings": list(self.rings), "plugboard": list(self.plugboard)}


def _read(path: str | Path | None, default: str) -> dict:
    source = Path(path) if path is not None else files("encrypted_radio").joinpath("data", default)
    with source.open("rb") as stream:
        data = stream.read(1_048_577)
    if len(data) > 1_048_576:
        raise ValueError("configuration exceeds 1 MiB")
    return json.loads(data.decode("utf-8"))


def load_machine(path: str | Path | None = None) -> Machine:
    return Machine.from_dict(_read(path, "machine.json"))


def load_key(path: str | Path | None = None, machine: Machine | None = None) -> Key:
    return Key.from_dict(_read(path, "example-key.json"), machine or load_machine())
