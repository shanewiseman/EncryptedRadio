"""ITU-R M.1677 ordinary ASCII Morse characters (not procedural signals)."""

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--",
    "Z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--",
    "4": "....-", "5": ".....", "6": "-....", "7": "--...", "8": "---..",
    "9": "----.", ".": ".-.-.-", ",": "--..--", ":": "---...",
    "?": "..--..", "'": ".----.", "/": "-..-.", "-": "-....-",
    "(": "-.--.", ")": "-.--.-", '"': ".-..-.", "=": "-...-",
    "+": ".-.-.", "@": ".--.-.",
}
REVERSE_MORSE = {value: key for key, value in MORSE.items()}
PROFILES = ("checked", "raw", "text")


def normalize_character(character: str, profile: str) -> str:
    """Normalize text only; cipher transports must preserve exact symbols."""
    if ord(character) > 127:
        raise ValueError("Morse input must be ASCII")
    if profile == "text":
        if character.isspace():
            return " "
        character = character.upper()
    if character not in MORSE:
        raise ValueError(f"character has no ordinary Morse representation: {character!r}")
    return character
