"""Reciprocal Enigma-style rotor transform (not modern cryptography)."""
from .config import ALPHABET, Key, Machine


class RotorMachine:
    def __init__(self, machine: Machine, key: Key, positions: tuple[int, ...] | None = None):
        self.machine = machine
        self.key = key
        self.positions = list(positions if positions is not None else key.positions)
        if len(self.positions) != len(key.rotors) or any(type(v) is not int or not 0 <= v < 49 for v in self.positions):
            raise ValueError("rotor positions must match the selected rotor stack")
        self.forward = [tuple(ALPHABET.index(ch) for ch in machine.rotors[name].wiring) for name in key.rotors]
        self.inverse = [tuple(wiring.index(i) for i in range(49)) for wiring in self.forward]
        self.notches = [machine.rotors[name].notches for name in key.rotors]
        self.reflector = tuple(ALPHABET.index(ch) for ch in machine.reflector)
        self.plugs = list(range(49))
        for left, right in key.plugboard:
            a, b = ALPHABET.index(left), ALPHABET.index(right)
            self.plugs[a], self.plugs[b] = b, a

    def step(self) -> None:
        marked = {len(self.positions) - 1}
        for i in range(1, len(self.positions)):
            if self.positions[i] in self.notches[i]:
                marked.update((i - 1, i))
        for i in marked:
            self.positions[i] = (self.positions[i] + 1) % 49

    def transform(self, symbols: str) -> str:
        if any(ch not in ALPHABET for ch in symbols):
            raise ValueError("ciphertext must contain only transport alphabet characters")
        result = []
        for ch in symbols:
            self.step()
            value = self.plugs[ALPHABET.index(ch)]
            for i in range(len(self.positions) - 1, -1, -1):
                offset = self.positions[i] - self.key.rings[i]
                value = (self.forward[i][(value + offset) % 49] - offset) % 49
            value = self.reflector[value]
            for i in range(len(self.positions)):
                offset = self.positions[i] - self.key.rings[i]
                value = (self.inverse[i][(value + offset) % 49] - offset) % 49
            result.append(ALPHABET[self.plugs[value]])
        return "".join(result)
