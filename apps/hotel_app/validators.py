from django.core.exceptions import ValidationError


def validate_digits(value):
    if not value or not value.isascii() or not value.isdigit():
        raise ValidationError('En este campo solo se admiten números.')


def validate_letters_and_spaces(value):
    if not value or not any(character.isalpha() for character in value):
        raise ValidationError('En este campo solo se admiten letras.')
    if any(not character.isalpha() and character != ' ' for character in value):
        raise ValidationError('En este campo solo se admiten letras.')
