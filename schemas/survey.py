from pydantic import BaseModel, field_validator


def _likert_validator(cls, v, values=None):
    """Validate that a Likert scale value is between 1 and 7 (or None)."""
    if v is not None:
        if not isinstance(v, int) or v < 1 or v > 7:
            raise ValueError("Value must be between 1 and 7")
    return v


def validate_likert_fields(form_data: dict, field_names: list[str],
                           min_val: int = 1, max_val: int = 7) -> str | None:
    """Validate Likert fields from a form dict. Returns error message or None."""
    for name in field_names:
        val = form_data.get(name)
        if val is not None:
            if not isinstance(val, int) or val < min_val or val > max_val:
                return f"Please provide valid responses (values must be between {min_val} and {max_val})."
    return None


_VALID_GENDERS = {"Male", "Female", "Non-binary", "Other", "Prefer not to say"}
_VALID_RACES = {
    "White", "Black or African American", "Hispanic or Latino", "Asian",
    "Native American or Alaska Native", "Native Hawaiian or Pacific Islander",
    "Other", "Prefer not to say",
}
_VALID_EDUCATIONS = {
    "Less than high school", "High school diploma or equivalent", "Some college",
    "Associate's degree", "Bachelor's degree", "Master's degree",
    "Doctoral degree", "Professional degree",
}
_VALID_PARTISANSHIPS = {
    "Very liberal", "Liberal", "Moderate", "Conservative",
    "Very conservative", "Prefer not to say",
}


class DemographicsSubmit(BaseModel):
    age: int | None = None
    gender: str | None = None
    race: str | None = None
    education: str | None = None
    partisanship: str | None = None

    @field_validator("age")
    @classmethod
    def _validate_age(cls, v):
        if v is not None and (v < 18 or v > 120):
            raise ValueError("Age must be between 18 and 120")
        return v

    @field_validator("gender")
    @classmethod
    def _validate_gender(cls, v):
        if v is not None and v not in _VALID_GENDERS:
            raise ValueError("Please select a valid gender option")
        return v

    @field_validator("race")
    @classmethod
    def _validate_race(cls, v):
        if v is not None and v not in _VALID_RACES:
            raise ValueError("Please select a valid race/ethnicity option")
        return v

    @field_validator("education")
    @classmethod
    def _validate_education(cls, v):
        if v is not None and v not in _VALID_EDUCATIONS:
            raise ValueError("Please select a valid education option")
        return v

    @field_validator("partisanship")
    @classmethod
    def _validate_partisanship(cls, v):
        if v is not None and v not in _VALID_PARTISANSHIPS:
            raise ValueError("Please select a valid political orientation")
        return v
