"""SQLAlchemy models mirroring db/schema.sql.
Run schema.sql directly against Postgres for the pgvector setup;
these models are for querying/inserting from the app layer.
"""
import uuid
from datetime import datetime
 
from sqlalchemy import (
    Column, String, Text, ForeignKey, DateTime, Numeric, Integer,
    ARRAY, Boolean, Date, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector
 
Base = declarative_base()
 
 
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=True)  # nullable for backward-compat with any users created before auth existed
    role = Column(String, nullable=False, default="candidate")  # candidate
    # Subscription tier: 'free' | 'pro' | 'max'. Enforced server-side (see
    # app/services/tiers.py). Defaults to free; set via billing later.
    tier = Column(String, nullable=False, default="free")
    created_at = Column(DateTime, default=datetime.utcnow)
 
    profiles = relationship("Profile", back_populates="user")
 
 
class Profile(Base):
    __tablename__ = "profiles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    northstar = Column(Text, nullable=False)
    final_idea = Column(Text)
    timeframe = Column(String)
    stage = Column(String)
    priorities = Column(ARRAY(String))
    skills = Column(Text)
    dealbreakers = Column(Text)
    location_pref = Column(String)
    target_types = Column(ARRAY(String))
    # Applicant contact details used to actually fill out real application forms
    # (Pro auto-submit) and to head a generated resume. Optional - when absent,
    # auto-submit safely hands off any form that requires them rather than
    # submitting an incomplete application.
    full_name = Column(String)
    phone = Column(String)
    # Explicit, revocable permission for Kaidostar to use the above details (and a
    # resume built from the user's entries) to fill out and SUBMIT applications to
    # employers on the user's behalf. Defaults False: without it, auto-submit never
    # runs and the app hands the finished application back for the user to submit.
    auto_submit_consent = Column(Boolean, nullable=False, default=False)
    is_athlete = Column(Boolean, nullable=False, default=False)
    sport = Column(String)
    level = Column(String)
    career_direction = Column(String)
    achievements = Column(Text)
    # Athlete recruiting specifics collected by the survey (previously dropped on
    # save because the Profile table lacked columns for them). These matter for
    # recruiting matches: position, graduation year, target division, GPA.
    position = Column(String)
    grad_year = Column(String)
    target_division = Column(String)
    gpa = Column(String)
    is_student = Column(Boolean, nullable=False, default=False)
    intended_major = Column(String)
    grade_level = Column(String)
    target_schools = Column(Text)
    interests = Column(Text)
    student_achievements = Column(Text)
    is_current = Column(Boolean, default=True)
    auto_apply_enabled = Column(Boolean, nullable=False, default=False)
    auto_apply_threshold = Column(Integer, nullable=False, default=80)
    notification_preferences = Column(JSONB, default=lambda: {"scan": True, "auto_apply": True, "outreach_sent": True, "applications_approved": True})
    created_at = Column(DateTime, default=datetime.utcnow)
 
    user = relationship("User", back_populates="profiles")
 
 
class Listing(Base):
    __tablename__ = "listings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    org = Column(String, nullable=False)
    type = Column(String, nullable=False)
    location = Column(String)
    description = Column(Text)
    tags = Column(ARRAY(String))
    deadline = Column(Date)
    apply_url = Column(String, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    salary_is_predicted = Column(Boolean, nullable=True)  # None means genuinely no salary data at all - absent is honestly different from a real, disclosed 0
    embedding = Column(Vector(512), nullable=True)  # None until embedded - see app/services/embeddings.py
 
 
class MatchScore(Base):
    __tablename__ = "match_scores"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    score_pct = Column(Numeric(5, 2), nullable=False)
    goal_match_tags = Column(ARRAY(String))
    skill_match_tags = Column(ARRAY(String))
    rationale = Column(Text)
    scan_cycle = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class Outcome(Base):
    __tablename__ = "outcomes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)  # applied/interview/rejected/ghosted/offer
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class RoadmapMilestone(Base):
    __tablename__ = "roadmap_milestones"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    success_criteria = Column(Text)
    estimated_timeframe = Column(String)
    first_action = Column(Text)
    resource = Column(Text)
    risk = Column(Text)
    if_it_works = Column(Text)
    if_it_stalls = Column(Text)
    target_stage = Column(Integer, nullable=False)
    status = Column(String, default="planned")
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class RoadmapSummary(Base):
    __tablename__ = "roadmap_summaries"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    summary = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class ChatMemory(Base):
    __tablename__ = "chat_memory"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class Application(Base):
    __tablename__ = "applications"
    # One application per (user, listing). The code dedups via a check-then-insert
    # ("already_existed"), which races: two concurrent applies (a double-click, or the
    # auto-apply scan racing a manual apply) both pass the "existing?" check and insert
    # two rows - a duplicate AI draft plus polluted calibration. This DB constraint is
    # the real guarantee; the insert path catches the IntegrityError and returns the
    # existing row. (Requires db/schema_additions_dedup_constraints.sql on existing DBs.)
    __table_args__ = (UniqueConstraint("user_id", "listing_id", name="uq_applications_user_listing"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    draft_content = Column(Text)
    confidence_pct = Column(Numeric(5, 2))
    status = Column(String, default="pending_review")
    sendable_at = Column(DateTime)
    sent_at = Column(DateTime)
    # How/where an accepted application was actually delivered. "email" means a
    # real email went to sent_to_address (a best-effort general company address);
    # "web" means the real route is the posting's own form and the finished draft
    # was handed to the user to submit (the app cannot auto-submit arbitrary web
    # forms). Both nullable - populated only once a delivery is attempted.
    sent_channel = Column(String, nullable=True)
    sent_to_address = Column(String, nullable=True)
    auto_generated = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    factors_snapshot = Column(JSONB, nullable=True)  # the score_listing() factor breakdown at creation time - without this, there's no way to later learn which TYPES of signal actually predicted success for this user
    counterfactual_confidence_pct = Column(Numeric(5, 2), nullable=True)  # what the score WOULD have been without personalized factor weighting - without this, there's no way to check whether personalization is actually helping this user or just moving the number around
    draft_flagged_terms = Column(JSONB, nullable=True)  # numbers or specific timing claims (e.g. "summer") that appear in draft_content but nowhere in the real source material - see draft_application()'s fabrication check
 
 
class SavedListing(Base):
    __tablename__ = "saved_listings"
    # One save per (user, listing) - the check-then-insert in save_listing races the
    # same way. DB-enforced; the route catches the IntegrityError as "already saved".
    __table_args__ = (UniqueConstraint("user_id", "listing_id", name="uq_saved_listings_user_listing"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class DismissedListing(Base):
    """A real, explicit 'not interested, never show this again' record
    - the backend counterpart to the frontend's dismissListing. Kept
    as its own table (not a status flag on Application) since a
    person can genuinely dismiss a listing they never applied to at
    all - dismissal and application are two separate, real actions.
    """
    __tablename__ = "dismissed_listings"
    # One dismissal per (user, listing) - same check-then-insert race. DB-enforced;
    # the route catches the IntegrityError as "already dismissed".
    __table_args__ = (UniqueConstraint("user_id", "listing_id", name="uq_dismissed_listings_user_listing"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class Notification(Base):
    __tablename__ = "notifications"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    detail = Column(Text)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class AdmissionsSnapshot(Base):
    """A timestamped point in a student's readiness trajectory. Persisting these
    is what lets the app show progress over real time - the one thing a stateless
    chatbot cannot do. `avg` is the overall readiness signal (0-100); `per_school`
    and `evidence` capture the detail for that moment."""
    __tablename__ = "admissions_snapshots"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    avg = Column(Integer, nullable=False)
    per_school = Column(JSONB)
    evidence = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class CareerDiscoveryResult(Base):
    __tablename__ = "career_discovery_results"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    answers = Column(JSONB, nullable=False)
    directions = Column(JSONB, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class OutreachEmail(Base):
    __tablename__ = "outreach_emails"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    to_address = Column(String, nullable=False)
    address_verified = Column(Boolean, nullable=False, default=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="drafted")  # drafted / sent / failed
    auto_generated = Column(Boolean, nullable=False, default=False)
    leadership_grounded = Column(Boolean, nullable=False, default=False)  # True only if real, current leadership statements were found and referenced
    leadership_research_sources = Column(JSONB, nullable=True)  # [{url, title}] - the real sources behind a leadership_grounded draft, for the recipient's own verification
    created_at = Column(DateTime, default=datetime.utcnow)
    # One outreach draft per (user, listing): both draft_outreach_for_match and its
    # leadership-grounded sibling dedup with a check-then-insert (the "already_existed"
    # path). Like applications/saved/dismissed, that only holds under concurrency with
    # a DB-level UNIQUE - without it, a scheduler auto-outreach racing a manual draft
    # (or a double-click) inserts TWO drafts the user could send to the same contact
    # twice. Constraint + IntegrityError handling in the insert paths close the race.
    __table_args__ = (UniqueConstraint("user_id", "listing_id", name="uq_outreach_user_listing"),)
 
 
class SocialPost(Base):
    """A private progress journal entry. tag_value/tag_label hold a
    real roadmap stage number and title - the one real tagging style
    left now that candidate is the only account role (athletic traits
    are a survey-detected characteristic of a candidate, not a
    separate role, and tutor has been removed entirely).
    """
    __tablename__ = "social_posts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    body = Column(Text, nullable=False)
    video_url = Column(String)
    tag_value = Column(String)
    tag_label = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)
 
 
class AthleteEvent(Base):
    """A tracked deadline or trial opportunity for a student-athlete -
    a tryout, camp, combine, or application deadline, optionally tied
    to a specific roadmap stage.
    """
    __tablename__ = "athlete_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    org = Column(String)
    event_type = Column(String, nullable=False)  # tryout / camp / combine / application_deadline / other
    event_date = Column(Date)
    roadmap_stage = Column(Integer)
    roadmap_stage_title = Column(String)
    status = Column(String, nullable=False, default="upcoming")  # upcoming / attended / passed / missed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class AthleteOutreach(Base):
    """A draft/edit/send email + cold-call script for reaching a coach
    or staff member. Separate from OutreachEmail since it isn't tied
    to a real listing row - grounded in a free-text description of
    who to reach instead.
    """
    __tablename__ = "athlete_outreach"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_description = Column(Text, nullable=False)
    to_address = Column(String, nullable=False)
    address_verified = Column(Boolean, nullable=False, default=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    cold_call_script = Column(Text)
    roadmap_stage = Column(Integer)
    roadmap_stage_title = Column(String)
    status = Column(String, nullable=False, default="drafted")  # drafted / sent / failed
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class AthleteRoadmapMilestone(Base):
    """Real backend roadmap for athletes - mirrors RoadmapMilestone,
    plus if_it_works/if_it_stalls branching which the candidate
    backend roadmap doesn't even have yet (only the frontend does).
    """
    __tablename__ = "athlete_roadmap_milestones"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    success_criteria = Column(Text)
    estimated_timeframe = Column(String)
    first_action = Column(Text)
    resource = Column(Text)
    risk = Column(Text)
    if_it_works = Column(Text)
    if_it_stalls = Column(Text)
    target_stage = Column(Integer, nullable=False)
    status = Column(String, default="planned")
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class AthleteRoadmapSummary(Base):
    __tablename__ = "athlete_roadmap_summaries"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    summary = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class ResumeEntry(Base):
    """A single real, user-provided fact about their experience -
    a job, an education entry, or a project. entry_type + title +
    org + dates are all things the user states directly; raw_description
    is their own plain-language account of what they did. The AI-
    polish step (see app/services/resume_builder.py) is only ever
    allowed to strengthen the PHRASING of raw_description into
    resume-style language - never to add a fact, metric, or
    achievement the user didn't put here themselves. This table is
    the real source of truth a resume gets built from; nothing about
    a person's work history is ever generated from scratch.
    """
    __tablename__ = "resume_entries"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entry_type = Column(String, nullable=False)  # work / education / project
    title = Column(String, nullable=False)  # job title, degree, or project name
    org = Column(String)  # employer, school, or None for a personal project
    start_date = Column(String)  # free text ("Jun 2024") - real dates people give are rarely full ISO dates
    end_date = Column(String)  # free text, or "Present"
    raw_description = Column(Text, nullable=False)  # the user's own plain-language account - never AI-generated
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class ResumeDocument(Base):
    """The most recently generated resume for a user - polished
    bullet points and a summary line, always traceable back to the
    real ResumeEntry rows it was built from (entries_snapshot keeps
    the exact raw_description text used, so a later edit to an entry
    doesn't silently make an old generated resume look like it was
    based on something the user never actually said).
    """
    __tablename__ = "resume_documents"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    summary_line = Column(Text)
    polished_entries = Column(JSONB, nullable=False)  # [{entry_id, title, org, dates, bullets: [str]}]
    entries_snapshot = Column(JSONB, nullable=False)  # raw_description text as it existed at generation time
    generated_at = Column(DateTime, default=datetime.utcnow)
 
 
class ApiQuotaTracker(Base):
    """Tracks real daily call volume against a specific external
    API's documented rate limit - built after actually checking
    Adzuna's real, current free-tier terms (roughly 1,000 calls a
    month, about 33 a day) rather than assuming the ingestion
    pipeline's call volume was safely within some unverified "should
    be fine" range. One row per (api_name, date); see
    app/services/ingestion.py's check_and_reserve_quota for how this
    gets used to gracefully skip rather than blindly exceed a real,
    external limit.
    """
    __tablename__ = "api_quota_tracker"
    api_name = Column(String, primary_key=True)
    date = Column(String, primary_key=True)  # YYYY-MM-DD, not a DateTime - this is a daily bucket key, not a timestamp
    call_count = Column(Integer, default=0)
 
 
class CompanyLeadershipResearch(Base):
    """A real cache, not just a nice-to-have: without this, a
    candidate viewing a company's leadership research and then
    deciding to draft an outreach email would trigger the same real,
    billed web-search call twice for the same company - and every
    other candidate applying to the same company would each trigger
    their own redundant search too. Keyed by a normalized company
    name (lowercased, stripped) so "Acme Inc" and "acme inc " hit the
    same cached row. See app/services/market_research.py's
    get_or_research_company_leadership for how this gets checked
    before ever making a real search call.
    """
    __tablename__ = "company_leadership_research"
    company_name_normalized = Column(String, primary_key=True)
    company_name_display = Column(String, nullable=False)  # the real, as-typed name, for display
    leaders = Column(JSONB, nullable=False)
    priorities_summary = Column(Text, nullable=False)
    sources = Column(JSONB, nullable=False)
    researched_at = Column(DateTime, default=datetime.utcnow)
 
 
class StrategicPositionCache(Base):
    """A real cache for the strategic-position analysis, keyed by
    user_id - but unlike CompanyLeadershipResearch above, this one
    invalidates on CONTENT, not time. A company's real leadership
    doesn't change day to day, so a 30-day time window is safe there.
    This person's own real applications/roadmap/saved listings CAN
    change within minutes - someone could send a new application and
    immediately re-check their position, and a time-based cache would
    show them a stale read that doesn't reflect what they just did.
    input_signature is a short hash of their real, current data shape
    (count + latest timestamp per source) - cheap to compute, and any
    genuine change to their real underlying data produces a different
    signature, forcing a fresh analysis. No genuine change means the
    same signature, so the cached result is reused correctly. See
    app/services/strategy.py's get_or_analyze_strategic_position for
    how this gets checked before ever making a real API call.
    """
    __tablename__ = "strategic_position_cache"
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    input_signature = Column(String, nullable=False)
    result = Column(JSONB, nullable=False)
    analyzed_at = Column(DateTime, default=datetime.utcnow)
 
 
class StrategicPositionHistory(Base):
    """A real, append-only log of every strategic-position analysis
    ever run for a person - distinct from StrategicPositionCache
    above, which only ever holds the single most recent result and
    exists purely to avoid a redundant API call. This table is what
    makes the feature genuinely longitudinal rather than a single,
    isolated snapshot each time: without a real record of what was
    true last time, a new analysis has no way to say whether real,
    measurable progress happened since then, or whether things have
    genuinely stalled - it can only ever describe the current moment
    in isolation. See app/services/strategy.py's
    get_or_analyze_strategic_position for how the most recent entry
    here gets fed into the next real analysis as genuine context.
    """
    __tablename__ = "strategic_position_history"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    input_signature = Column(String, nullable=False)
    result = Column(JSONB, nullable=False)
    analyzed_at = Column(DateTime, default=datetime.utcnow)
 
 
class EngagementSuggestion(Base):
    """A real, AI-drafted suggestion for engaging with a specific,
    real post the person pasted in - never something scraped or
    auto-posted on their behalf (see draft_engagement_suggestion's
    own docstring for why: LinkedIn's API terms explicitly prohibit
    both automated scraping and automated posting/commenting on a
    person's behalf, so the person always supplies the real post
    content themselves, and always reviews and posts the suggestion
    manually - this only ever drafts the words, never acts).
 
    accept_token is a real, unguessable, single-use token embedded in
    the email link - accepting a suggestion means marking it reviewed
    and copyable in-app, not auto-posting anything anywhere.
    communication_log is a real, append-only record of what happened
    after (a reply the person got, a follow-up question) so a later
    suggestion can genuinely build on what actually happened, not
    just the original post in isolation - mirrors the same real
    "history informs the next suggestion" pattern already proven in
    StrategicPositionHistory above, applied to this different feature.
    """
    __tablename__ = "engagement_suggestions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    post_content = Column(Text, nullable=False)  # the real post text the person pasted in
    poster_context = Column(Text)  # what the person told us about who posted it (role, company, etc.) - optional, their own words
    drafted_question = Column(Text, nullable=False)
    is_smaller_decision_maker = Column(Boolean, default=False)  # the AI's real, stated read on whether this poster looks like a more accessible, smaller-scale decision-maker
    reasoning = Column(Text)  # why this question, in plain language - never hidden from the person who has to decide whether to actually post it
    status = Column(String, nullable=False, default="drafted")  # drafted / emailed / accepted / declined
    accept_token = Column(String, unique=True)
    email_sent_at = Column(DateTime)
    responded_at = Column(DateTime)
    communication_log = Column(JSONB, default=list)  # [{at, note}] - real, user-entered updates on what happened after
    created_at = Column(DateTime, default=datetime.utcnow)
 
