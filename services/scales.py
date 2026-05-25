"""Central scale registry — single source of truth for all questionnaire scales.

To add a new Likert scale:
1. Add DB columns in models/survey.py + Alembic migration
2. Add a LikertScale(...) entry to LIKERT_SCALES below

Everything else (schema validation, router handling, template rendering,
CSV export) adapts automatically.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LikertScale:
    prefix: str                    # "sen_a" -> fields sen_a_1..sen_a_4
    page: str                      # "A", "B", "C", or "demographics"
    title: str                     # Academic construct name (used in export)
    items: tuple[str, ...]         # Question texts
    description: str = ""          # Sub-heading (e.g. Likert instruction)
    display_title: str = ""        # Neutral UI heading; empty = no heading shown
    min_val: int = 1
    max_val: int = 7
    low_anchor: str = "Strongly Disagree"
    high_anchor: str = "Strongly Agree"

    @property
    def field_names(self) -> list[str]:
        return [f"{self.prefix}_{i}" for i in range(1, len(self.items) + 1)]


@dataclass(frozen=True)
class CustomItem:
    """Non-standard item (custom radio options, unique validation range)."""
    field_name: str
    page: str
    min_val: int
    max_val: int


# ---------------------------------------------------------------------------
# Registry — order within a page determines question numbering
# ---------------------------------------------------------------------------

LIKERT_SCALES: list[LikertScale] = [
    # ── Page A ──
    LikertScale("sen_a", "A", "Agency", (
        "The conversational partner in the first round had the ability to solve problems.",
        "The conversational partner in the first round had its own personality.",
        "The conversational partner in the first round was capable of communication.",
        "The conversational partner in the first round could experience emotions.",
    ), display_title="------------------------------------------------------------------"),
    LikertScale("fee_h", "A", "Feeling Heard", (
        "The conversational partner in the first round was interested in what I had said.",
        "The conversational partner in the first round encouraged me to speak openly.",
        "The conversational partner in the first round understood my thoughts.",
        "The conversational partner in the first round cared about me.",
    ), display_title="------------------------------------------------------------------"),
    LikertScale("ce", "A", "Conversational Engagement", (
        "During the conversation, I could feel the emotions the partner in the first round portrayed.",
        "The conversation with the partner in the first round was enjoyable.",
        "I was mentally involved in the conversation with the partner in the first round.",
        "While engaged in the conversation, I had a vivid image of the partner in the first round.",
    ), display_title="------------------------------------------------------------------"),

    # ── Page B ──
    LikertScale("ail", "B", "AI Literacy", (
        "I know the most important concepts of the topic 'artificial intelligence.'",
        "I can assess what the limitations and opportunities of using an AI are.",
        "I can use AI applications to make my everyday life easier.",
        "I can use artificial intelligence meaningfully to achieve my everyday goals.",
    ), display_title="------------------------------------------------------------------",
    description="Please rate the following statements on a scale from 1 (Strongly Disagree) to 7 (Strongly Agree)."),

    # ── Demographics ──
    LikertScale("rlg", "demographics", "Religiosity", (
        "Religion is important in my life.",
        "I attend religious services regularly.",
        "My religious beliefs influence my daily decisions.",
        "I consider myself to be a religious person.",
    ), display_title="------------------------------------------------------------------", 
    description="Please rate the following on a scale from 1 (Strongly Disagree) to 7 (Strongly Agree)."),

    # ── Page C: Outcome Variables ──
    # No display_title — items flow naturally without section headers

    # Conversation outcomes
    LikertScale("cga", "C", "Conversation Goal Attainment", (
        "I accomplished the task objective.",
        "I felt emotionally supported.",
    )),
    LikertScale("cinf", "C", "Perceived Conversation Informativeness", (
        "This conversation was informative.",
        "I learned something from this conversation.",
    )),
    LikertScale("ccg", "C", "Common Ground Perception", (
        "My partner and I were on the same page during the conversation.",
        "I felt my partner and I shared a mutual understanding of the topic during the conversation.",
        "It was easy to establish shared references with my partner during the conversation.",
    )),
    LikertScale("cmu", "C", "Perceived Mutual Understanding", (
        "My partner and I both understood each other well during the conversation.",
    )),
    LikertScale("cpu", "C", "Perceived Understanding", (
        "Satisfied",
        "Relaxed",
        "Pleasant",
        "Good",
    ), description="The following terms refer to feelings relevant when people attempt to make themselves understood. Please rate the degree to which you felt each during the conversation.", low_anchor="Very little", high_anchor="Very great"),
    LikertScale("ccs", "C", "Communication Satisfaction", (
        "The other person let me know that I was communicating effectively.",
        "Nothing was accomplished.",
        "I would like to have another conversation like this one.",
        "The other person genuinely wanted to get to know me.",
    ), description="Please indicate the degree to which you agree or disagree that each statement describes your conversation."),
    LikertScale("cconn", "C", "Connection Felt During Conversations", (
        'I felt "in sync" with my partner.',
        "I felt like my partner and I shared a lot in common.",
        "I felt that my partner and I saw the world in the same way.",
        "My partner were able to relate to my experiences.",
    )),
    LikertScale("cenj", "C", "Enjoyment", (
        "I enjoyed this conversation.",
        "I thought this conversation was engaging.",
        "I had an interesting conversation with this person.",
    )),
    LikertScale("cfsi", "C", "Intention to Engage in Future Social Interactions", (
        "How likely do you want to have another conversation with someone else?",
    ), low_anchor="Very unlikely", high_anchor="Very likely"),

    # Partner perceptions
    LikertScale("pce", "C", "Perceived Communication Effectiveness", (
        "My partner achieved what he or she apparently wanted to achieve in the conversation.",
        "For my partner, it was a useless conversation.",
        "My partner was effective.",
        "Our conversation was very unsuccessful.",
    ), description="Please indicate the degree to which you agree or disagree that each statement describes your partner's communication."),
    LikertScale("pca", "C", "Perceived Communication Appropriateness", (
        "My partner said several things that seemed out of place in the conversation.",
        "My partner was a smooth conversationalist.",
        "Everything my partner said was appropriate.",
        "My partner's conversation was very suitable to the situation.",
    )),
    LikertScale("pael", "C", "Active-Empathic Listening", (
        "My partner was sensitive to what I was not saying.",
        "My partner was aware of what I implied but did not say.",
        "My partner understood how I felt.",
        "My partner listened for more than just the spoken words.",
    ), description="Please indicate the degree to which you agree or disagree that each statement describes your partner's listening behavior."),
    LikertScale("pta", "C", "Interpersonal Attraction — Task", (
        "If I wanted to get things done, I could probably depend on my partner.",
        "My partner would be a poor problem solver.",
        "I couldn't get anything accomplished with my partner.",
        "I have confidence in my partner's ability to get the job done.",
    ), description="Please indicate the degree to which you agree or disagree that each statement describes your partner."),
    LikertScale("psa", "C", "Interpersonal Attraction — Social", (
        "I think my partner could be a friend of mine.",
        "I would like to have a friendly chat with my partner.",
        "It would be difficult to meet and talk with my partner.",
        "We could never establish a personal friendship with each other.",
    )),
    LikertScale("phom", "C", "Homophily — Attitude", (
        "This person thinks like me.",
        "This person doesn't behave like me.",
        "This person is different from me.",
        "This person shares my values.",
    ), description="Please indicate the degree to which you agree or disagree that each statement describes your partner."),
    LikertScale("psos", "C", "Self-Other Similarity", (
        "How much do you think you have in common with your partner?",
        "How similar do you think you and your partner are likely to be?",
    ), low_anchor="Very little", high_anchor="Very great"),
    LikertScale("pwca", "C", "Willingness to Communicate Again", (
        "I would be willing to have another conversation with this person.",
        "I would enjoy talking with this person again.",
    )),
    LikertScale("pwsa", "C", "Willingness to Seek Future Advice", (
        "I would be willing to seek advice from this person in the future.",
        "I would be willing to cooperate with this person in the future.",
    )),
    LikertScale("plik", "C", "Liking", (
        "My partner was likable.",
        "I liked my partner.",
        "I would enjoy spending time with my partner.",
        "I disliked my partner.",
    )),
    LikertScale("pec", "C", "Empathic Concern", (
        "I felt warm toward my partner.",
        "I felt compassion for my partner.",
        "I feel sympathetic toward my partner.",
    )),
    LikertScale("ppec", "C", "Perceived Empathic Concern", (
        "My partner felt warm toward me.",
        "My partner felt compassion for me.",
        "My partner felt sympathetic toward me.",
    )),

    # Individual differences
    LikertScale("dhm", "C", "Dehumanization Propensity", (
        "I was easily upset by seeing others in distress.",
        "I felt deeply upset when I saw others suffering, and I was often motivated to help.",
        "I was not a prejudiced person.",
        "I was a very social person.",
    )),
    LikertScale("iri_pt", "C", "Perspective Taking (IRI)", (
        "Before criticizing somebody, I try to imagine how I would feel if I were in their place.",
        "If I'm sure I'm right about something, I don't waste much time listening to other people's arguments.",
        "I sometimes try to understand my friends better by imagining how things look from their perspective.",
        "I believe that there are two sides to every question and try to look at them both.",
    ), description="Please indicate the extent that each statement describes you."),
    LikertScale("iri_ec", "C", "Empathic Concern (IRI)", (
        "When I see someone being taken advantage of, I feel kind of protective toward them.",
        "When I see someone being treated unfairly, I sometimes don't feel very much pity for them.",
        "I often have tender, concerned feelings for people less fortunate than me.",
        "I would describe myself as a pretty soft-hearted person.",
    )),
    LikertScale("iri_pd", "C", "Personal Distress (IRI)", (
        "When I see someone who badly needs help in an emergency, I go to pieces.",
        "I sometimes feel helpless when I am in the middle of a very emotional situation.",
        "In emergency situations, I feel apprehensive and ill-at-ease.",
        "I am usually pretty effective in dealing with emergencies.",
    )),
]
CUSTOM_ITEMS: list[CustomItem] = [
    CustomItem("manip_check", "B", 1, 3),
    CustomItem("ai_usage", "B", 1, 7),
]

# DB field name -> CSV header name (for fields that need renaming)
CUSTOM_ITEM_EXPORT_MAP: dict[str, str] = {
    "manip_check": "partner_label_check",
}

# Number of structural demographics fields (not Likert, not custom)
DEMOGRAPHICS_STRUCTURAL_FIELDS = 5  # age, gender, race, education, partisanship


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_page_scales(page: str) -> list[LikertScale]:
    return [s for s in LIKERT_SCALES if s.page == page]


def get_page_likert_fields(page: str) -> list[str]:
    fields: list[str] = []
    for s in get_page_scales(page):
        fields.extend(s.field_names)
    return fields


def get_page_custom_items(page: str) -> list[CustomItem]:
    return [ci for ci in CUSTOM_ITEMS if ci.page == page]


def get_all_page_fields(page: str) -> list[str]:
    """All form field names for a page (custom + Likert)."""
    fields = [ci.field_name for ci in get_page_custom_items(page)]
    fields.extend(get_page_likert_fields(page))
    return fields


def get_total_likert_count() -> int:
    """Total number of Likert fields across all pages."""
    return sum(len(s.items) for s in LIKERT_SCALES)
