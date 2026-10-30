"""The "about you" questions asked at sign-up, collected for research.

The register page renders its choices from here and /api/session cleans what
the browser sends against the same lists, so the two cannot drift apart.
"""

GENDERS = [
    ("female", "Female"),
    ("male", "Male"),
    ("non_binary", "Non-binary"),
    ("other", "Other"),
    ("prefer_not_to_say", "Prefer not to say"),
]

AGE_MIN, AGE_MAX = 8, 100
SCHOOL_MAX = 120

COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola",
    "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus",
    "Belgium", "Belize", "Benin", "Bhutan", "Bolivia",
    "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria",
    "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia", "Cameroon", "Canada",
    "Central African Republic", "Chad", "Chile", "China", "Colombia",
    "Comoros", "Congo", "Costa Rica", "Côte d'Ivoire", "Croatia", "Cuba",
    "Cyprus", "Czechia", "Democratic Republic of the Congo", "Denmark",
    "Djibouti", "Dominica", "Dominican Republic", "Ecuador", "Egypt",
    "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini",
    "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia", "Georgia",
    "Germany", "Ghana", "Greece", "Grenada", "Guatemala", "Guinea",
    "Guinea-Bissau", "Guyana", "Haiti", "Honduras", "Hong Kong", "Hungary",
    "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel",
    "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati",
    "Kosovo", "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho",
    "Liberia", "Libya", "Liechtenstein", "Lithuania", "Luxembourg", "Macao",
    "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta",
    "Marshall Islands", "Mauritania", "Mauritius", "Mexico", "Micronesia",
    "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique",
    "Myanmar", "Namibia", "Nauru", "Nepal", "Netherlands", "New Zealand",
    "Nicaragua", "Niger", "Nigeria", "North Korea", "North Macedonia",
    "Norway", "Oman", "Pakistan", "Palau", "Palestine", "Panama",
    "Papua New Guinea", "Paraguay", "Peru", "Philippines", "Poland",
    "Portugal", "Puerto Rico", "Qatar", "Romania", "Russia", "Rwanda",
    "Saint Kitts and Nevis", "Saint Lucia",
    "Saint Vincent and the Grenadines", "Samoa", "San Marino",
    "São Tomé and Príncipe", "Saudi Arabia", "Senegal", "Serbia",
    "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia",
    "Solomon Islands", "Somalia", "South Africa", "South Korea",
    "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname", "Sweden",
    "Switzerland", "Syria", "Taiwan", "Tajikistan", "Tanzania", "Thailand",
    "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago", "Tunisia",
    "Türkiye", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States", "Uruguay",
    "Uzbekistan", "Vanuatu", "Vatican City", "Venezuela", "Vietnam",
    "Yemen", "Zambia", "Zimbabwe",
]

_GENDER_KEYS = {key for key, _ in GENDERS}
_COUNTRY_SET = set(COUNTRIES)


def clean(raw):
    """Keep only the well-formed answers from a sign-up payload.

    Anything missing or malformed is dropped rather than rejected: by the time
    this runs the Firebase account already exists, and a stray value should
    not stop someone signing in. The form itself insists on all four.
    """
    if not isinstance(raw, dict):
        return {}
    out = {}

    gender = raw.get("gender")
    if gender in _GENDER_KEYS:
        out["gender"] = gender

    try:
        age = int(raw.get("age"))
    except (TypeError, ValueError):
        age = None
    if age is not None and AGE_MIN <= age <= AGE_MAX:
        out["age"] = age

    school = " ".join(str(raw.get("school") or "").split())[:SCHOOL_MAX]
    if school:
        out["school"] = school

    nationality = raw.get("nationality")
    if nationality in _COUNTRY_SET:
        out["nationality"] = nationality

    return out
