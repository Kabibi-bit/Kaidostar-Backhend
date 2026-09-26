"""School knowledge base + admissions-advice tailoring.

The backend mirror of the frontend school KB (kaidostar/state.js). Holds the
curated, source-verified profiles for the US T30 + top UK universities -
each with its real motto, what it values, tailored guidance, and a
"what accepted students actually did" pattern - plus the logic that
tailors advice to a student's specific target schools.

Honesty rules carried over from the frontend, deliberately:
- Data is curated and source-verified, NOT generated per-request, so
  there are no hallucinated mottos, acceptance rates, or admit patterns.
- UK schools use the real UK course-specific academic model, which is
  genuinely different from the US holistic model - never a US copy.
- Nothing here promises admission; guidance is school-general and honest.
- Schools NOT in this curated set get an explicit "general guidance"
  fallback rather than fabricated school-specific claims.

Keep this file in sync with kaidostar/state.js SCHOOLS. If you change one,
change the other - a drift test in the test suite guards this.
"""

SCHOOLS = [
    {
        "name": "Harvard University",
        "aka": [
            "harvard"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~3.6%",
        "region": "Cambridge, MA",
        "dataDepth": "deep",
        "motto": "\"Veritas\" — Latin for \"truth.\" Harvard's mission is to educate citizens and citizen-leaders through a transformative liberal-arts education.",
        "values": [
            "intellectual vitality",
            "a genuine spike",
            "impact on others",
            "authentic voice"
        ],
        "guidance": "Harvard rejects the vast majority of valedictorians - grades and scores get you considered, not admitted. What separates admits is a genuine, deep \"spike\" (a demonstrated, exceptional strength in one area) plus evidence you affect the people around you. Its motto \"Veritas\" rewards intellectual honesty and real curiosity - reference the value through your own experience, never by name-dropping.",
        "acceptedPattern": "Public analyses of admitted students consistently show a clear spike, usually built from extracurriculars and honors rather than coursework - e.g. an admit who progressed over four years from environmental-club member to regional coordinator, showing rising responsibility and measurable impact. The recurring pattern: sustained depth in one or two things, framed around real, quantifiable change - not a long list of shallow memberships."
    },
    {
        "name": "Stanford University",
        "aka": [
            "stanford"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "Stanford, CA",
        "dataDepth": "deep",
        "motto": "\"Die Luft der Freiheit weht\" — German for \"the wind of freedom blows,\" chosen to enshrine fearless, unfettered inquiry (\"studies blossom and the minds move\").",
        "values": [
            "intellectual vitality",
            "initiative",
            "a distinctive angle",
            "building things"
        ],
        "guidance": "Stanford prizes intellectual curiosity for its own sake and students who build or start things - its \"intellectual vitality\" essay directly probes this. The motto reflects a culture of fearless inquiry, so a self-started project or genuine intellectual obsession reads far stronger than a prestigious-but-passive membership.",
        "acceptedPattern": "Admitted profiles tend to show a distinctive personal angle - the \"what makes you, you\" - and evidence of self-directed initiative (a founded project, a curiosity taken further than assigned). Depth and an authentic, specific essay voice recur far more than a broad resume."
    },
    {
        "name": "Massachusetts Institute of Technology (MIT)",
        "aka": [
            "mit",
            "massachusetts institute of technology"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "Cambridge, MA",
        "dataDepth": "deep",
        "motto": "\"Mens et Manus\" — Latin for \"Mind and Hand.\" MIT's founding ideal is education for practical application: learning by doing, theory joined to making.",
        "values": [
            "hands-on making",
            "STEM depth",
            "collaboration",
            "using knowledge for good"
        ],
        "guidance": "MIT wants makers, not just high scorers. Its motto \"Mens et Manus\" (Mind and Hand) means concrete evidence you build, tinker, and solve real problems is what tips an application. MIT genuinely values collaboration over competition (\"you cannot graduate from MIT by yourself\") - show teamwork and mutual support, not just individual wins.",
        "acceptedPattern": "By MIT's own admissions materials and analyses of admitted profiles, the Maker Portfolio is often the real tie-breaker: admitted students show \"the stuff they have built\" - a coded app on GitHub, a robotics project, a restored engine, a hackathon build, or olympiad/research work with genuine hands-on depth. Building something tangible beats winning a generic award."
    },
    {
        "name": "California Institute of Technology (Caltech)",
        "aka": [
            "caltech",
            "california institute of technology"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~3.8%",
        "region": "Pasadena, CA",
        "dataDepth": "deep",
        "motto": "\"The truth shall make you free\" (Veritas vos liberabit). Caltech is a tiny, intensely rigorous science-and-engineering institute (~2,200 students).",
        "values": [
            "capacity for rigor",
            "scholarly character",
            "deep STEM ability",
            "lifting up peers"
        ],
        "guidance": "Caltech is uniquely, unapologetically about raw scientific and mathematical ability at an extreme level. Its own admissions site names three qualities: capacity for Caltech rigor, scholarly character (integrity, resilience, generosity), and readiness to thrive in a brutally fast pace. Deep math/science preparation and genuine research or problem-solving matter more here than a well-rounded profile.",
        "acceptedPattern": "Admits show exceptional depth in advanced math and science - olympiads, serious research, self-driven technical work - and, per Caltech, \"elevate the people learning alongside them.\" It is one of the few top schools where pure STEM firepower and scholarly character outweigh breadth of activities."
    },
    {
        "name": "Princeton University",
        "aka": [
            "princeton"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "Princeton, NJ",
        "dataDepth": "deep",
        "motto": "\"Dei sub numine viget\" — \"Under God's power she flourishes,\" paired with the informal ethos \"in the nation's service and the service of humanity.\"",
        "values": [
            "scholarship",
            "service",
            "intellectual depth",
            "writing"
        ],
        "guidance": "Princeton has a strong undergraduate focus and service ethos. It weighs intellectual depth and strong writing heavily - the graded written paper it requests is read seriously. Sustained scholarship and genuine service commitments matter more than breadth.",
        "acceptedPattern": "Admitted students commonly pair real intellectual depth (research, a scholarly pursuit) with authentic, sustained service - and write exceptionally well. Because Princeton reads a graded academic paper, demonstrated writing quality is a recurring differentiator."
    },
    {
        "name": "Yale University",
        "aka": [
            "yale"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "New Haven, CT",
        "dataDepth": "deep",
        "motto": "\"Lux et Veritas\" — Latin for \"Light and Truth.\"",
        "values": [
            "intellectual engagement",
            "community impact",
            "distinctive voice",
            "the arts and humanities"
        ],
        "guidance": "Yale reads for how you engage ideas and community - it famously weighs \"what you'll bring to the residential college.\" A distinctive essay voice and genuine engagement (including arts and humanities, which Yale values strongly) stand out more than a purely stats-driven profile.",
        "acceptedPattern": "Admitted profiles often show a person who visibly contributes to a community and brings a distinctive voice - Yale wants to picture what you add to residential-college life. Engagement and character recur as much as raw achievement."
    },
    {
        "name": "University of Pennsylvania (UPenn)",
        "aka": [
            "upenn",
            "penn",
            "university of pennsylvania"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~6%",
        "region": "Philadelphia, PA",
        "dataDepth": "deep",
        "motto": "\"Leges sine moribus vanae\" — \"Laws without morals are in vain,\" reflecting Benjamin Franklin's founding emphasis on practical, ethical purpose.",
        "values": [
            "pre-professional focus",
            "a specific \"why Penn\"",
            "interdisciplinary drive",
            "purpose"
        ],
        "guidance": "Penn is the most pre-professional Ivy and admits with real attention to fit with its specific schools (Wharton, Engineering, Nursing, CAS) and cross-disciplinary programs. A concrete, specific \"why Penn / why this program\" and evidence you'll use your education purposefully read very well.",
        "acceptedPattern": "Admits typically show a focused direction that maps onto a specific Penn school or program, plus a clear, researched reason for Penn specifically - not a generic Ivy application. Demonstrated purpose and pre-professional initiative recur."
    },
    {
        "name": "Columbia University",
        "aka": [
            "columbia"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "New York, NY",
        "dataDepth": "deep",
        "motto": "\"In lumine Tuo videbimus lumen\" — \"In Thy light shall we see light.\"",
        "values": [
            "intellectual breadth",
            "the Core Curriculum",
            "engagement with NYC",
            "ideas across disciplines"
        ],
        "guidance": "Columbia's famous Core Curriculum means it looks for genuine intellectual breadth and love of big ideas across disciplines, plus students who will engage with New York City. Its distinctive \"list\" supplements (books, media you enjoy) reward authentic intellectual curiosity, not a curated performance.",
        "acceptedPattern": "Admits show wide-ranging intellectual curiosity and specific, honest engagement with ideas (and the city) - the Core rewards thinkers comfortable across the humanities and sciences, not just single-track specialists."
    },
    {
        "name": "Brown University",
        "aka": [
            "brown"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~5%",
        "region": "Providence, RI",
        "dataDepth": "deep",
        "motto": "\"In Deo Speramus\" — \"In God we hope.\" Brown is known for its Open Curriculum (no core requirements).",
        "values": [
            "intellectual self-direction",
            "curiosity",
            "fit with the Open Curriculum",
            "initiative"
        ],
        "guidance": "Brown's Open Curriculum means it specifically seeks self-directed students who thrive without a rigid structure. Show intellectual independence and a clear sense of what you'd do with that freedom - a student who needs to be told what to study is a poor fit, and Brown's essays test exactly this.",
        "acceptedPattern": "Admits demonstrate genuine intellectual self-direction - self-designed projects, unusual course combinations, pursuits driven by their own curiosity. A convincing account of why the Open Curriculum fits how you learn recurs strongly."
    },
    {
        "name": "Dartmouth College",
        "aka": [
            "dartmouth"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~5.3%",
        "region": "Hanover, NH",
        "dataDepth": "deep",
        "motto": "\"Vox clamantis in deserto\" — \"A voice crying out in the wilderness.\" Dartmouth is the smallest, most undergraduate-focused Ivy.",
        "values": [
            "undergraduate focus",
            "community",
            "a bold, independent voice",
            "engagement with a tight-knit campus"
        ],
        "guidance": "Dartmouth prizes undergraduate teaching and a close community, so it reads for students who will actively contribute to a small, tight-knit campus. A bold, authentic voice and evidence you engage deeply with people and place fit its \"voice in the wilderness\" identity.",
        "acceptedPattern": "Admits often show genuine community contribution and a distinctive, independent voice - Dartmouth wants people who will show up for a small campus, not just excel in isolation."
    },
    {
        "name": "Duke University",
        "aka": [
            "duke"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~6%",
        "region": "Durham, NC",
        "dataDepth": "deep",
        "motto": "\"Eruditio et Religio\" — \"Knowledge and Faith.\"",
        "values": [
            "ambition with balance",
            "collaboration",
            "breadth and depth",
            "real-world application"
        ],
        "guidance": "Duke looks for high-achieving students who combine serious ambition with collaboration and range (it prizes both intellectual and, often, athletic/extracurricular energy). A specific \"why Duke\" and evidence of applying your interests in the real world read well.",
        "acceptedPattern": "Admits tend to pair strong academics with genuine collaborative leadership and applied impact - the recurring theme is ambition balanced with contribution to a team or community, not solo achievement alone."
    },
    {
        "name": "Johns Hopkins University",
        "aka": [
            "johns hopkins",
            "jhu",
            "hopkins"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~6%",
        "region": "Baltimore, MD",
        "dataDepth": "deep",
        "motto": "\"Veritas vos liberabit\" — \"The truth shall set you free.\" America's first research university.",
        "values": [
            "research",
            "collaboration",
            "hands-on inquiry",
            "depth in a field"
        ],
        "guidance": "Hopkins, the original US research university, explicitly values students who do real research and collaborate. It is especially strong in the sciences and medicine, and its essays reward concrete evidence of inquiry and teamwork over polished generalities.",
        "acceptedPattern": "Admits frequently show genuine research or hands-on inquiry (labs, independent projects) and collaborative work - Hopkins publicly emphasizes collaboration over competition, and that shows up in who gets in."
    },
    {
        "name": "Northwestern University",
        "aka": [
            "northwestern"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~7%",
        "region": "Evanston, IL",
        "dataDepth": "deep",
        "motto": "\"Quaecumque sunt vera\" — \"Whatsoever things are true.\"",
        "values": [
            "a specific \"why Northwestern\"",
            "interdisciplinary interests",
            "balance of academics and passions",
            "fit"
        ],
        "guidance": "Northwestern weighs demonstrated interest and fit heavily, and its \"Why Northwestern\" essay is genuinely important - it wants students who have researched its specific programs (journalism, engineering, theatre, its quarter system). Balanced, cross-disciplinary students who can name exactly why Northwestern do well.",
        "acceptedPattern": "Admits show a well-researched, specific fit with Northwestern's programs and culture, plus a balance of academic strength and real passions. Generic applications fare worse; specificity recurs among those admitted."
    },
    {
        "name": "University of Chicago",
        "aka": [
            "uchicago",
            "university of chicago",
            "u chicago"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~5%",
        "region": "Chicago, IL",
        "dataDepth": "deep",
        "motto": "\"Crescat scientia; vita excolatur\" — \"Let knowledge grow from more to more; and so be human life enriched.\"",
        "values": [
            "intellectual playfulness",
            "rigor for its own sake",
            "original thinking",
            "loving ideas"
        ],
        "guidance": "UChicago is famous for its quirky, open-ended essay prompts that test genuine intellectual playfulness and original thinking - \"the life of the mind\" is its whole identity. It rewards students who love ideas for their own sake and can think unconventionally, not resume-optimizers.",
        "acceptedPattern": "Admits consistently show intellectual originality and a real delight in ideas - the standout essays take an unusual prompt somewhere genuinely creative and rigorous. Loving the thinking itself, visibly, is the recurring signal."
    },
    {
        "name": "Cornell University",
        "aka": [
            "cornell"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~7%",
        "region": "Ithaca, NY",
        "dataDepth": "deep",
        "motto": "\"I would found an institution where any person can find instruction in any study.\" — Ezra Cornell.",
        "values": [
            "fit with a specific college",
            "breadth of access",
            "applied and practical study",
            "a clear academic direction"
        ],
        "guidance": "Cornell admits by specific college (Engineering, Arts & Sciences, CALS, Hotel, ILR, etc.), each with its own priorities, so fit with your chosen college and a clear \"why this college/major\" is central. Its \"any person, any study\" ethos values applied, practical study alongside theory.",
        "acceptedPattern": "Admits show a clear academic direction that genuinely matches their chosen Cornell college, with evidence of engagement in that specific field - the per-college structure makes focused, well-matched applications recur among those admitted."
    },
    {
        "name": "Rice University",
        "aka": [
            "rice"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~8%",
        "region": "Houston, TX",
        "dataDepth": "deep",
        "motto": "\"Letters, Science, Art.\" Rice is small, collaborative, and known for its residential-college culture.",
        "values": [
            "collaboration",
            "fit with the residential-college culture",
            "depth in a field",
            "a distinctive perspective"
        ],
        "guidance": "Rice is small and collaborative, with a strong residential-college system and a famous supplemental question (\"what perspective would you add?\"). It reads for students who will add something distinctive to a tight community and go deep in their field.",
        "acceptedPattern": "Admits show real depth in an area plus a genuine, specific sense of what they'd contribute to Rice's collaborative community - the recurring theme is distinctive perspective and fit, not just stats."
    },
    {
        "name": "Vanderbilt University",
        "aka": [
            "vanderbilt",
            "vandy"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~5%",
        "region": "Nashville, TN",
        "dataDepth": "deep",
        "motto": "\"Crescere Aude\" — \"Dare to grow.\"",
        "values": [
            "leadership",
            "collaboration",
            "ambition with balance",
            "contribution to community"
        ],
        "guidance": "Vanderbilt (among the most selective now) looks for high-achieving students with real leadership and a collaborative, community-minded streak. Its \"dare to grow\" ethos rewards evidence of stretching yourself and lifting others, alongside strong academics.",
        "acceptedPattern": "Admits pair strong academics with demonstrated leadership and community contribution - growth, initiative, and helping others recur alongside raw achievement."
    },
    {
        "name": "University of Notre Dame",
        "aka": [
            "notre dame",
            "nd"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~9%",
        "region": "Notre Dame, IN",
        "dataDepth": "deep",
        "motto": "\"Vita, Dulcedo, Spes\" — \"Life, Sweetness, Hope.\" A Catholic university with a strong service and community identity.",
        "values": [
            "service",
            "character and values",
            "community",
            "a sense of purpose"
        ],
        "guidance": "Notre Dame has a distinctive Catholic mission and a strong service ethos, and it reads for character, values, and genuine community commitment alongside academics. Authentic service and a sense of purpose fit its identity - and its essays probe for exactly that.",
        "acceptedPattern": "Admits often show sustained, genuine service and a clear values-driven purpose, plus real community involvement - character and contribution recur strongly, consistent with its mission."
    },
    {
        "name": "Georgetown University",
        "aka": [
            "georgetown"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~12%",
        "region": "Washington, DC",
        "dataDepth": "deep",
        "motto": "\"Utraque Unum\" — \"Both into one.\" A Jesuit university strong in government, international affairs, and service.",
        "values": [
            "service (\"cura personalis\")",
            "engagement with the world",
            "intellectual seriousness",
            "purpose"
        ],
        "guidance": "Georgetown, Jesuit and DC-based, is strong in politics, international relations, and service, and its ethos \"cura personalis\" (care for the whole person) shapes what it seeks. It uses its own application (not the Common App) and values intellectual seriousness plus genuine engagement with the world.",
        "acceptedPattern": "Admits show real engagement with the world (service, politics, global issues) and intellectual seriousness - purpose and contribution recur, fitting its Jesuit, service-oriented mission."
    },
    {
        "name": "University of California, Berkeley",
        "aka": [
            "uc berkeley",
            "berkeley",
            "cal"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~11%",
        "region": "Berkeley, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" A public research powerhouse.",
        "values": [
            "academic excellence",
            "overcoming challenges",
            "contribution to community",
            "the UC PIQs"
        ],
        "guidance": "Berkeley uses the UC application (no Common App essay) and its Personal Insight Questions carry real weight. It reads holistically with genuine attention to context and challenges overcome. For CS/engineering it is especially competitive - demonstrated rigor in your intended field matters.",
        "acceptedPattern": "Strong Personal Insight Question responses that show real contribution and growth in context recur among admits. Berkeley values demonstrated excellence within a student's own circumstances, not just absolute stats."
    },
    {
        "name": "University of California, Los Angeles (UCLA)",
        "aka": [
            "ucla",
            "uc los angeles"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~9%",
        "region": "Los Angeles, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" The most-applied-to university in the US.",
        "values": [
            "academic excellence",
            "the UC PIQs",
            "contribution and context",
            "breadth with depth"
        ],
        "guidance": "UCLA (UC application, PIQs matter) reads holistically with real attention to context and contribution. It is extremely competitive overall. Strong, specific Personal Insight Questions and demonstrated impact in your community stand out more than stats alone.",
        "acceptedPattern": "Like Berkeley, UCLA admits tend to show strong, specific Personal Insight Question responses and real community impact framed in the context of their own circumstances."
    },
    {
        "name": "University of Michigan",
        "aka": [
            "michigan",
            "umich",
            "university of michigan"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~18%",
        "region": "Ann Arbor, MI",
        "dataDepth": "deep",
        "motto": "\"Artes, Scientia, Veritas\" — \"Arts, Knowledge, Truth.\"",
        "values": [
            "academic rigor",
            "community contribution",
            "specific \"why Michigan\"",
            "leadership"
        ],
        "guidance": "Michigan values genuine \"why Michigan / why this community\" specificity and sustained contribution. It reads rigor in context. A thoughtful, specific supplemental essay and real depth in a couple of activities matter more than a generic strong-student profile.",
        "acceptedPattern": "A specific, well-researched \"why Michigan\" supplement and sustained depth in a few activities recur among admits far more than a generically strong record."
    },
    {
        "name": "University of North Carolina at Chapel Hill (UNC)",
        "aka": [
            "unc",
            "unc chapel hill",
            "north carolina"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~17%",
        "region": "Chapel Hill, NC",
        "dataDepth": "deep",
        "motto": "\"Lux Libertas\" — \"Light and Liberty.\" The oldest US public university.",
        "values": [
            "service and public good",
            "leadership",
            "contribution to community",
            "academic strength"
        ],
        "guidance": "UNC (much more selective for out-of-state applicants) has a strong public-service ethos and reads for leadership and community contribution alongside academics. Genuine service and a clear sense of contributing to the public good fit its identity.",
        "acceptedPattern": "Admits show academic strength plus real service and leadership - contribution to community recurs, consistent with UNC's public-good mission. Out-of-state admission is notably more competitive."
    },
    {
        "name": "Carnegie Mellon University",
        "aka": [
            "carnegie mellon",
            "cmu"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~11%",
        "region": "Pittsburgh, PA",
        "dataDepth": "deep",
        "motto": "\"My heart is in the work.\" — Andrew Carnegie.",
        "values": [
            "depth in the intended program",
            "a technical or artistic portfolio",
            "fit with the specific college",
            "rigor"
        ],
        "guidance": "CMU admits by specific college/program, so depth and fit with your exact intended field is central - a portfolio or concrete body of work (technical or artistic) is often what tips it. Its ethos \"my heart is in the work\" rewards visible dedication. Generalist profiles fare worse here than at more holistic schools; go deep in your lane.",
        "acceptedPattern": "Admits usually present a real body of work in their intended program - a portfolio, a technical project, an artistic reel - showing the dedication Carnegie's \"heart is in the work\" ethos points to."
    },
    {
        "name": "Emory University",
        "aka": [
            "emory"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~13%",
        "region": "Atlanta, GA",
        "dataDepth": "deep",
        "motto": "\"Cor prudentis possidebit scientiam\" — \"The wise heart seeks knowledge.\"",
        "values": [
            "intellectual curiosity",
            "service",
            "fit and demonstrated interest",
            "strength in the health sciences/humanities"
        ],
        "guidance": "Emory reads for genuine intellectual curiosity and demonstrated interest, and is especially strong for pre-med and the humanities. A specific \"why Emory\" and authentic engagement with your field read well; it values fit and character over pure prestige-chasing.",
        "acceptedPattern": "Admits show real curiosity and often service, with a specific reason for Emory - demonstrated interest and authentic fit recur alongside strong academics."
    },
    {
        "name": "University of Virginia (UVA)",
        "aka": [
            "uva",
            "university of virginia",
            "virginia"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~17%",
        "region": "Charlottesville, VA",
        "dataDepth": "deep",
        "motto": "Founded by Thomas Jefferson on ideals of self-governance and honor; known for its student-run Honor System.",
        "values": [
            "character and honor",
            "leadership",
            "community and self-governance",
            "academic strength"
        ],
        "guidance": "UVA (much more selective out-of-state) has a distinctive honor and student-self-governance culture, and reads for character, leadership, and community contribution. Its short, specific supplements reward authentic voice and a real sense of how you'd engage its community.",
        "acceptedPattern": "Admits pair academic strength with genuine leadership and character - contribution to community and a fit with UVA's honor culture recur, especially given how competitive out-of-state admission is."
    },
    {
        "name": "Washington University in St. Louis (WashU)",
        "aka": [
            "washu",
            "wustl",
            "washington university",
            "washington university in st louis"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~11%",
        "region": "St. Louis, MO",
        "dataDepth": "deep",
        "motto": "\"Per veritatem vis\" — \"Strength through truth.\"",
        "values": [
            "demonstrated interest",
            "academic depth",
            "collaboration",
            "fit"
        ],
        "guidance": "WashU weighs demonstrated interest meaningfully and is strong in the sciences, medicine, and business. A specific \"why WashU,\" genuine engagement, and real academic depth read well - it rewards students who clearly want WashU specifically.",
        "acceptedPattern": "Admits show strong academics plus clear, demonstrated interest and fit - a specific reason for WashU and authentic engagement recur among those admitted."
    },
    {
        "name": "University of Southern California (USC)",
        "aka": [
            "usc",
            "university of southern california",
            "southern cal"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~10%",
        "region": "Los Angeles, CA",
        "dataDepth": "deep",
        "motto": "\"Palmam qui meruit ferat\" — \"Let whoever earns the palm bear it.\"",
        "values": [
            "a distinctive talent or angle",
            "interdisciplinary drive",
            "fit with a specific school (film, business, engineering)",
            "initiative"
        ],
        "guidance": "USC is strong in film, business, engineering, and the arts, and admits with real attention to fit with its specific schools and to a distinctive talent or angle. A clear \"why this USC school\" and evidence of a genuine, developed passion read well.",
        "acceptedPattern": "Admits often show a distinctive, developed talent that maps onto a specific USC school, plus interdisciplinary energy - a clear angle and fit recur more than a generic strong profile."
    },
    {
        "name": "New York University (NYU)",
        "aka": [
            "nyu",
            "new york university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~12%",
        "region": "New York, NY",
        "dataDepth": "deep",
        "motto": "\"Perstare et praestare\" — \"To persevere and to excel.\"",
        "values": [
            "genuine fit with NYU's global/urban identity",
            "demonstrated interest",
            "academic rigor"
        ],
        "guidance": "NYU reads for genuine fit with its urban, global identity and rewards demonstrated interest and a specific \"why NYU.\" It has no single \"type,\" but a clear reason you want NYU specifically (not just New York) and real depth in your field help a lot.",
        "acceptedPattern": "A convincing, specific \"why NYU\" (the programs, the global identity - not just the city) plus demonstrated interest recur among admits, alongside solid rigor in the intended field."
    },
    {
        "name": "Tufts University",
        "aka": [
            "tufts"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~10%",
        "region": "Medford, MA",
        "dataDepth": "deep",
        "motto": "\"Pax et Lux\" — \"Peace and Light.\" Known for its quirky, thoughtful supplemental essays.",
        "values": [
            "intellectual playfulness",
            "a distinctive voice",
            "fit and demonstrated interest",
            "global engagement"
        ],
        "guidance": "Tufts is known for creative, open-ended supplements that reward authentic voice and intellectual playfulness (its \"why Tufts\" and quirky prompts genuinely matter). It values students who are thoughtful, distinctive, and clearly want Tufts specifically.",
        "acceptedPattern": "Admits show a distinctive, genuine voice in the supplements and real fit with Tufts - the standout applications lean into the quirky prompts sincerely rather than playing it safe."
    },
    {
        "name": "Georgia Institute of Technology",
        "aka": [
            "georgia tech",
            "gatech",
            "georgia institute of technology"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~16%",
        "region": "Atlanta, GA",
        "dataDepth": "deep",
        "motto": "\"Progress and Service.\"",
        "values": [
            "STEM rigor",
            "hands-on projects",
            "fit with the major",
            "problem-solving"
        ],
        "guidance": "Georgia Tech is strongly major-focused - fit with your intended (especially STEM) program matters a lot, and admission can differ sharply by major. Demonstrated rigor and real projects in your field, plus a clear \"why this major,\" read very well. Slightly less essay-driven than the Ivies, more focused on academic fit.",
        "acceptedPattern": "Admits typically show clear rigor in the intended major plus concrete projects (a build, a competition, applied work) that prove genuine engagement with the field - and a specific, credible reason for that major."
    },
    {
        "name": "University of Oxford",
        "aka": [
            "oxford",
            "oxford university",
            "university of oxford"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~13% (course-dependent)",
        "region": "Oxford, England",
        "dataDepth": "deep",
        "motto": "\"Dominus illuminatio mea\" — \"The Lord is my light.\"",
        "values": [
            "deep subject knowledge",
            "academic potential",
            "ability to think under pressure",
            "fit for the tutorial system"
        ],
        "guidance": "UK admissions are fundamentally different from the US: Oxford cares almost entirely about ACADEMIC ability and potential in your one chosen subject - not well-roundedness or a broad activity list. Its own guidance: \"show how deeply you have engaged with your subject, above and beyond school.\" Most courses require an admissions test (e.g. TMUA, TARA) and an interview that probes how you think. Your UCAS personal statement should be overwhelmingly about your subject.",
        "acceptedPattern": "Successful applicants demonstrate subject obsession that goes far beyond the syllabus - wider reading, engaging with real problems in the field, and articulating ideas clearly. In interviews, admits think aloud and handle unfamiliar problems rather than reciting facts. Extracurriculars matter only if they connect to academic ability."
    },
    {
        "name": "University of Cambridge",
        "aka": [
            "cambridge",
            "cambridge university",
            "university of cambridge"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~16% (course-dependent)",
        "region": "Cambridge, England",
        "dataDepth": "deep",
        "motto": "\"Hinc lucem et pocula sacra\" — \"From here, light and sacred draughts\" (enlightenment and knowledge).",
        "values": [
            "exceptional subject ability",
            "academic depth",
            "supervision-system fit",
            "clear scientific/analytical thinking"
        ],
        "guidance": "Like Oxford, Cambridge is about pure academic ability in your chosen subject, assessed through your grades, a subject admissions test (e.g. TMUA, ESAT), your personal statement, and a rigorous interview. It also asks many applicants to complete extra questionnaires. Deep, demonstrated engagement with your subject - not breadth of activities - is what matters.",
        "acceptedPattern": "Admits show top-level performance in the relevant subjects plus genuine intellectual depth beyond the curriculum, and in interviews they reason through hard, unfamiliar problems calmly. The recurring signal is exceptional, demonstrated ability in the one subject - the UK system rewards specialists."
    },
    {
        "name": "Imperial College London",
        "aka": [
            "imperial",
            "imperial college",
            "imperial college london"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~14% (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "Imperial retired its Latin motto in 2020; today it centres science, engineering, medicine, and business for real-world benefit.",
        "values": [
            "STEM excellence",
            "course fit",
            "quantitative ability",
            "practical application of science"
        ],
        "guidance": "Imperial is a STEM-focused UK powerhouse - admission is course-specific and heavily academic, with most courses requiring an admissions test (e.g. TMUA, ESAT) and strong maths/science grades. Its new structured personal statement asks directly why the course and why you're ready. Show deep, genuine ability and interest in your specific subject.",
        "acceptedPattern": "Admits show strong quantitative ability and genuine subject engagement (projects, competitions, wider study) - Imperial is unapologetically academic and course-focused, so demonstrated STEM depth and test performance recur far more than breadth."
    },
    {
        "name": "London School of Economics (LSE)",
        "aka": [
            "lse",
            "london school of economics"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~9% (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "\"Rerum cognoscere causas\" — \"To understand the causes of things.\"",
        "values": [
            "analytical and quantitative ability",
            "deep interest in the social sciences",
            "academic writing",
            "course fit"
        ],
        "guidance": "LSE places arguably more weight on the personal statement than any other top UK university, because it does not interview - the statement is your only chance to show fit. Its guidance is explicit: it should be overwhelmingly academic, focused on your chosen social-science subject. Strong grades, often a maths test (TMUA), and demonstrated analytical engagement matter most.",
        "acceptedPattern": "Because LSE doesn't interview, admits stand out through an intensely academic personal statement - real engagement with economics/social science beyond the syllabus, wider reading, and clear analytical thinking. Top grades and (where required) strong test scores recur. Extracurriculars are near-irrelevant unless academically connected."
    },
    {
        "name": "University College London (UCL)",
        "aka": [
            "ucl",
            "university college london"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~30% (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "\"Cuncti adsint meritaeque expectent praemia palmae\" — \"Let all come who by merit deserve the most reward.\" Founded as a secular, inclusive alternative to Oxbridge.",
        "values": [
            "academic ability in the chosen course",
            "genuine subject interest",
            "breadth of London/UCL opportunity",
            "merit"
        ],
        "guidance": "UCL is a large, research-intensive UK university with course-specific admission. Founded to be open to all \"by merit,\" it reads for genuine academic ability and subject interest through your grades, personal statement, and (for some courses) an admissions test. As in all UK applications, focus the statement on your chosen subject, not a broad activity list.",
        "acceptedPattern": "Admits show solid-to-strong grades and clear, genuine engagement with their chosen subject in the personal statement. Requirements vary widely by course, but the recurring signal is academic fit and subject motivation, not well-roundedness."
    },
    {
        "name": "University of Edinburgh",
        "aka": [
            "edinburgh",
            "university of edinburgh"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "course-dependent",
        "region": "Edinburgh, Scotland",
        "dataDepth": "deep",
        "motto": "\"Nec temere, nec timide\" — \"Neither rashly, nor timidly.\"",
        "values": [
            "academic ability in the chosen course",
            "genuine subject interest",
            "independent thinking",
            "course fit"
        ],
        "guidance": "Edinburgh is a large, ancient, research-intensive UK university with course-specific admission driven mainly by grades and the personal statement (it generally does not interview for most subjects). As with all UK applications, make the statement overwhelmingly about your chosen subject and your academic readiness for it.",
        "acceptedPattern": "Admits show the required grades and a focused, subject-driven personal statement demonstrating genuine interest and independent thinking. Competitiveness varies significantly by course; academic fit is the recurring signal."
    },
    {
        "name": "University of Texas at Austin",
        "aka": [
            "ut austin",
            "university of texas",
            "ut",
            "texas",
            "ut-austin"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~29% overall (far lower for top majors)",
        "region": "Austin, TX",
        "dataDepth": "deep",
        "motto": "\"Disciplina Praesidium Civitatis\" — \"A cultivated mind is the guardian genius of democracy.\" A major public flagship with elite CS, business, and engineering.",
        "values": [
            "fit with the specific major",
            "genuine depth in your field",
            "a real 'why this major'",
            "academic rigor"
        ],
        "guidance": "UT Austin admits BY MAJOR, and this is the single most important thing to understand: the ~29% overall rate is misleading because top programs (CS, McCombs business, engineering) are dramatically harder - CS's Turing honors reportedly denies 85% of valedictorians and competitive CS applicants rank top 1-3% with 1500+ SAT. Texas residents in the top ~6% get automatic admission to the university (not necessarily the major). Write the ApplyTexas Topic A personal statement plus a major-specific short answer that shows genuine curiosity about THAT field, not 'CS/business at any top school.'",
        "acceptedPattern": "Admitted students to competitive majors show deep, specific experience in that exact field (real projects, research, competitions) plus top-percentile academics - and essays that engage the actual discipline (specific CS subareas, faculty research, real problems), not generic ambition. Generic 'why this major' essays are immediately less competitive. For non-impacted majors, a solid record and clear direction suffice."
    },
    {
        "name": "University of California, San Diego (UCSD)",
        "aka": [
            "ucsd",
            "uc san diego"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~25%",
        "region": "La Jolla, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" A top public research university (2nd in the world by some research measures) with a distinctive eight-college system.",
        "values": [
            "strong PIQs with specificity",
            "academic and research focus",
            "contribution and self-reflection",
            "fit with a college theme"
        ],
        "guidance": "UCSD uses the UC application - four of eight Personal Insight Questions (350 words each), the SAME essays across every UC campus, no separate supplement. Since admitted students' academics are uniformly strong, the PIQs are your real differentiator: they reward specificity, genuine self-reflection, and even honest vulnerability (what you found hard, how you improved) over polished bragging. UCSD is especially strong in STEM, and its eight-college system rewards showing where you'd fit.",
        "acceptedPattern": "Admits show strong GPAs plus PIQs with real specificity and reflection - a documented pattern is essays that reveal a genuine, sustained intellectual or community commitment (e.g. a student who led a marine-biology club, researched ocean acidification, and built underwater drones toward a clear goal). CS, engineering, and biology are the most competitive."
    },
    {
        "name": "University of California, Davis (UC Davis)",
        "aka": [
            "uc davis",
            "ucd",
            "davis"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~37%",
        "region": "Davis, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" World-leading in veterinary medicine, agriculture, and environmental science.",
        "values": [
            "strong PIQs",
            "academic focus",
            "community contribution",
            "fit with signature programs"
        ],
        "guidance": "UC Davis uses the UC application - four of eight Personal Insight Questions (350 words each), identical across all UC campuses. It's a well-rounded research university that's genuinely world-first in veterinary science, agriculture, and environmental studies. As with all UCs, the PIQs carry real weight and reward specificity and self-reflection; a clear academic direction (especially in its signature fields) helps.",
        "acceptedPattern": "Admits show solid academics and PIQs conveying genuine interest and contribution. Applicants with real depth in Davis's standout areas (vet/ag/environmental/sustainability) stand out; the recurring signal is specificity and growth in the PIQs, not just stats."
    },
    {
        "name": "University of California, Irvine (UC Irvine)",
        "aka": [
            "uc irvine",
            "uci",
            "irvine"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~25%",
        "region": "Irvine, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" A fast-rising research university strong in CS, biology, and public health.",
        "values": [
            "strong PIQs",
            "academic focus in your field",
            "contribution",
            "self-reflection"
        ],
        "guidance": "UC Irvine uses the UC application - four of eight Personal Insight Questions (350 words each), identical across all UC campuses. It's rising fast and especially strong in computer science, biological sciences, and public health. The PIQs are the key differentiator among academically-strong applicants; write with specificity and genuine reflection, and show focus in your intended field (top majors are more competitive).",
        "acceptedPattern": "Admits show strong academics and focused, specific PIQs. Competitiveness varies sharply by major - CS and biology are among the hardest - and the recurring signal is demonstrated interest plus reflective, specific essays."
    },
    {
        "name": "University of California, Santa Barbara (UCSB)",
        "aka": [
            "ucsb",
            "uc santa barbara"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~38%",
        "region": "Santa Barbara, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" A research university with standout physics, engineering, and materials science (and multiple Nobel laureates).",
        "values": [
            "strong PIQs",
            "intellectual curiosity",
            "empathy and contribution",
            "academic focus"
        ],
        "guidance": "UCSB uses the UC application - four of eight Personal Insight Questions (350 words each), identical across all UC campuses. It has genuinely elite physics, engineering, and materials-science programs. UCSB specifically values students who will positively contribute to campus and show empathy alongside achievement; write PIQs with specificity and real reflection, and show genuine intellectual interest.",
        "acceptedPattern": "Admits show solid academics and PIQs conveying real curiosity, contribution, and (UCSB emphasizes) empathy and character. Its top science/engineering programs are notably more competitive; specific, reflective essays recur."
    },
    {
        "name": "University of Wisconsin-Madison",
        "aka": [
            "wisconsin",
            "uw madison",
            "university of wisconsin",
            "uw-madison"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~43%",
        "region": "Madison, WI",
        "dataDepth": "deep",
        "motto": "\"Numen Lumen\" (\"God, our light\"), but its living ethos is the \"Wisconsin Idea\": that university knowledge should improve people's lives beyond the classroom.",
        "values": [
            "the Wisconsin Idea (real-world impact)",
            "academic rigor",
            "genuine involvement",
            "a clear direction"
        ],
        "guidance": "Wisconsin-Madison is a top public research university whose defining value is the \"Wisconsin Idea\" - knowledge applied for the public good, statewide and beyond. Its supplemental essay asks what you want to accomplish and how you'd contribute, so tie your interests to real-world impact. It reads for rigor plus genuine involvement; out-of-state and top majors (CS, business, engineering) are more competitive.",
        "acceptedPattern": "Admits show strong academics plus genuine involvement, and the strongest essays connect the applicant's interests to real-world contribution consistent with the Wisconsin Idea. A clear sense of how you'd use your education recurs."
    },
    {
        "name": "University of Illinois Urbana-Champaign (UIUC)",
        "aka": [
            "uiuc",
            "university of illinois",
            "illinois",
            "u of i"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~45% overall (far lower for engineering/CS)",
        "region": "Urbana-Champaign, IL",
        "dataDepth": "deep",
        "motto": "\"Learning and Labor.\" A public powerhouse with top-5-in-the-nation engineering and computer science.",
        "values": [
            "fit with the specific major",
            "genuine technical depth",
            "problem-solving",
            "a real 'why this major'"
        ],
        "guidance": "UIUC admits BY MAJOR, and its world-class engineering and CS programs (Grainger College) are dramatically more competitive than the ~45% overall rate - CS admits are near the very top of the applicant pool. Apply directly to the major you want and write essays showing genuine, specific technical interest and real projects. A clear 'why this major and why UIUC' matters; generic ambition doesn't compete for the top programs.",
        "acceptedPattern": "Admits to top engineering/CS programs show serious demonstrated technical depth - real projects, competitions, applied work - well beyond strong grades, plus essays engaging the specific field. For less-impacted majors, a solid record and clear direction suffice."
    },
    {
        "name": "University of Washington (UW)",
        "aka": [
            "uw",
            "university of washington",
            "udub"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~43% overall (far lower for CS)",
        "region": "Seattle, WA",
        "dataDepth": "deep",
        "motto": "\"Lux Sit\" — \"Let there be light.\" A major public research university with an elite CS program (the Allen School), plus top medicine and sciences.",
        "values": [
            "fit with the intended field",
            "real engagement and impact",
            "a clear direction",
            "genuine reflection"
        ],
        "guidance": "UW is a leading public research university where the Allen School of Computer Science is extremely competitive and effectively a separate, much harder admit than the ~43% overall rate. It reads holistically with two required essays (a personal statement and a short response) that reward genuine reflection and real engagement. Show demonstrated depth in your field; top majors (CS especially) require serious evidence.",
        "acceptedPattern": "Admits show strong academics and reflective essays showing real engagement or impact; CS/Allen School admits in particular show serious demonstrated technical depth. Fit with the intended field and authentic reflection recur."
    },
    {
        "name": "University of Florida (UF)",
        "aka": [
            "uf",
            "university of florida",
            "florida"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~24%",
        "region": "Gainesville, FL",
        "dataDepth": "deep",
        "motto": "\"Civium in moribus rei publicae salus\" — \"The welfare of the state depends on the character of its citizens.\" A top public flagship and an especially strong value.",
        "values": [
            "academic rigor",
            "genuine involvement and leadership",
            "a clear direction",
            "contribution"
        ],
        "guidance": "UF is a highly-ranked public flagship, strong across the board, that has become notably more selective. It reads for academic rigor plus genuine, sustained involvement and leadership. Its application rewards clear direction and real contribution to your community; the competitive Honors Program and top majors ask for more demonstrated depth.",
        "acceptedPattern": "Admits show strong academics with genuine involvement and leadership over time; the recurring signal is sustained commitment and contribution rather than a scattered activity list. Honors and top majors are more competitive."
    },
    {
        "name": "Michigan State University",
        "aka": [
            "michigan state",
            "msu",
            "mich state"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~83%",
        "region": "East Lansing, MI",
        "dataDepth": "deep",
        "motto": "\"Advancing Knowledge. Transforming Lives.\" A large land-grant flagship, pioneer of the land-grant model, strong in education, supply chain, and the sciences.",
        "values": [
            "academic readiness",
            "a clear direction",
            "involvement",
            "fit with the major/program"
        ],
        "guidance": "Michigan State is a large, accessible land-grant flagship (the original land-grant model) with a much higher overall admit rate, though its Honors College and top programs (supply-chain management, education, some sciences) are meaningfully more competitive. A solid academic record, a clear direction, and genuine involvement read well; it's a strong target/safety with real program strengths.",
        "acceptedPattern": "Admits generally clear a solid GPA and course-rigor bar with a clear academic direction; Honors College and standout programs reward additional demonstrated depth and involvement."
    },
    {
        "name": "Northeastern University",
        "aka": [
            "northeastern",
            "neu"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~5-6% overall (RD ~3.8%)",
        "region": "Boston, MA",
        "dataDepth": "deep",
        "motto": "\"Lux, Veritas, Virtus\" — \"Light, Truth, Courage.\" Defined by its co-op program (paid six-month professional placements integrated into the degree).",
        "values": [
            "co-op / experiential readiness",
            "demonstrated interest",
            "real-world initiative",
            "depth over breadth"
        ],
        "guidance": "Northeastern's entire identity is co-op, so it reads applications for students who will thrive in paid professional placements - show real-world initiative and readiness for hands-on work. It's one of the few top-30 schools that rates demonstrated interest 'very important' (open its emails, attend sessions, and strongly consider Early Decision, which roughly doubles your odds - RD is under 4%). There's no 'Why Northeastern' essay, so your interest and co-op fit must come through the Common App essay and activities.",
        "acceptedPattern": "A documented admit pattern: a student with a 3.8 GPA / 1460 SAT got in because her essay showed her teaching herself Python to analyze local water-quality data - the officer 'could picture her succeeding in co-op.' Self-taught skills and independently solving real problems beat titles; sustained depth beats a long list; and demonstrated interest genuinely moves the needle here."
    },
    {
        "name": "Tulane University",
        "aka": [
            "tulane"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~13% overall (RD reportedly under 3%)",
        "region": "New Orleans, LA",
        "dataDepth": "deep",
        "motto": "\"Non sibi, sed suis\" — \"Not for oneself, but for one's own.\" Strong in pre-med and STEM (it began as a medical school) with a built-in service requirement.",
        "values": [
            "demonstrated interest (heavily)",
            "service",
            "a genuine 'why Tulane / why New Orleans'",
            "a distinctive angle"
        ],
        "guidance": "Tulane is the demonstrated-interest school - it admits the vast majority of its class through Early Decision/Early Action, leaving a Regular Decision rate reportedly under 3%. If Tulane is a real choice, applying early and showing genuine engagement is the single biggest lever. It has a strong service ethos (service is built into the curriculum) and pre-med/STEM strength; a specific 'why Tulane and why New Orleans' plus real service read well.",
        "acceptedPattern": "Admits overwhelmingly come from the early rounds and show clear, genuine interest in Tulane specifically (visits, contact, a specific reason for New Orleans), often paired with real service. The recurring lesson: 'Tulane wants students who want Tulane' - demonstrated interest and applying early matter more here than at almost any peer."
    },
    {
        "name": "Purdue University",
        "aka": [
            "purdue",
            "purdue university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~43% overall (far lower for engineering/CS)",
        "region": "West Lafayette, IN",
        "dataDepth": "deep",
        "motto": "\"Education, Research, Service.\" A public flagship with world-class engineering, computer science, and aviation, admitting by college.",
        "values": [
            "fit with the specific major/college",
            "genuine technical depth",
            "a specific 'why Purdue'",
            "hands-on/applied work"
        ],
        "guidance": "Purdue's ~43% overall rate is misleading - engineering and CS are far more competitive (admitted engineers average ~3.85 GPA / ~1409 SAT), and you apply directly into a college (engineering starts in a First-Year Engineering program). Its 'Why Purdue' short answer rewards SPECIFICITY - name an actual lab, a specific sub-field ('robotics and autonomous sensing,' not 'engineering'), and pick one academic and one non-academic interest. Purdue uses rolling admission, so apply early.",
        "acceptedPattern": "Admits to competitive colleges show genuine major-fit rigor (strong math/science, real projects) and essays that reference specific Purdue programs, labs, or faculty rather than generic 'good engineering school' praise. Applying early in the rolling cycle and demonstrated technical depth recur."
    },
    {
        "name": "Wake Forest University",
        "aka": [
            "wake forest",
            "wfu"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~21%",
        "region": "Winston-Salem, NC",
        "dataDepth": "deep",
        "motto": "\"Pro Humanitate\" — \"For Humanity.\" Small, teaching-focused, and a pioneer of test-optional admissions.",
        "values": [
            "character and service",
            "authentic voice",
            "engagement and work ethic",
            "fit with a small community"
        ],
        "guidance": "Wake Forest has been test-optional since 2009 and genuinely means it - it states 'numbers rarely tell the whole story' and weighs the interview, essays, and personal qualities (life experience, work ethic, engagement) heavily. Its optional supplemental questions are read closely and reward authentic voice. It's small and teaching-focused with a 'Pro Humanitate' service ethos; show real character and how you'd engage a close community.",
        "acceptedPattern": "Admits stand out through authentic voice, character, and service rather than stats alone - Wake Forest deliberately de-emphasizes test scores and looks for the person behind the numbers. Doing the optional interview and engaging sincerely with the supplements recur among admits."
    },
    {
        "name": "Boston University (BU)",
        "aka": [
            "bu",
            "boston university"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~14%",
        "region": "Boston, MA",
        "dataDepth": "deep",
        "motto": "\"Learning, Virtue, Piety.\" A large private research university woven into the city of Boston, admitting by school/college.",
        "values": [
            "fit with a specific school",
            "academic rigor",
            "a genuine 'why BU'",
            "engagement with an urban campus"
        ],
        "guidance": "BU is a large urban research university that admits into its specific schools/colleges (e.g. Questrom business, engineering, CAS, COM), so fit with your intended school matters. Its supplemental essay asks why BU, and it rewards specificity about programs and the Boston setting. Strong academics plus a credible reason you want BU (not just 'a school in Boston') read well.",
        "acceptedPattern": "Admits show strong academics and a specific reason for BU and their intended college; the recurring signal is genuine fit and a clear academic direction rather than treating BU as an interchangeable big-city option."
    },
    {
        "name": "Boston College",
        "aka": [
            "bc",
            "boston college"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~15%",
        "region": "Chestnut Hill, MA",
        "dataDepth": "deep",
        "motto": "\"Ever to Excel\" (Aien Aristeuein). A Jesuit university with a formation ethos ('cura personalis' - care for the whole person) and a liberal-arts core.",
        "values": [
            "character and formation",
            "service",
            "reflective purpose",
            "intellectual and personal growth"
        ],
        "guidance": "Boston College is Jesuit, and its 'cura personalis' formation ethos genuinely shapes admissions - it reads for character, values, and a reflective sense of purpose alongside academics. Its supplemental prompts are often reflective/values-oriented (BC has asked distinctive questions about beliefs and purpose), so answer them with genuine self-reflection. Real service and a thoughtful sense of who you're becoming fit its identity.",
        "acceptedPattern": "Admits show strong academics plus genuine service and reflective depth in the essays - character and a values-driven purpose recur, consistent with BC's Jesuit formation mission."
    },
    {
        "name": "University of Rochester",
        "aka": [
            "rochester",
            "u of r",
            "university of rochester",
            "uofr"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~35%",
        "region": "Rochester, NY",
        "dataDepth": "deep",
        "motto": "\"Meliora\" — \"Ever Better.\" Open curriculum (no strict core) with standout optics, music (Eastman), and the sciences.",
        "values": [
            "intellectual self-direction",
            "fit with the open curriculum",
            "depth in a field",
            "curiosity"
        ],
        "guidance": "Rochester has a flexible open curriculum (the 'Rochester Curriculum' - no rigid general-ed requirements) and elite programs in optics, music (Eastman), and the sciences. Its 'Meliora' ethos and self-directed structure reward students who show intellectual independence and a clear sense of what they'd pursue with that freedom. Its essays ask how you'd use the open curriculum - answer specifically.",
        "acceptedPattern": "Admits show genuine curiosity and self-direction plus real depth in an area; a convincing account of why the open curriculum fits how you learn, and clear academic interests, recur among those admitted."
    },
    {
        "name": "Case Western Reserve University",
        "aka": [
            "case western",
            "cwru",
            "case"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~30%",
        "region": "Cleveland, OH",
        "dataDepth": "deep",
        "motto": "\"Thinking Beyond the Possible.\" A research-intensive university strong in engineering, the sciences, and pre-med.",
        "values": [
            "STEM and research strength",
            "demonstrated interest",
            "fit with the intended field",
            "problem-solving"
        ],
        "guidance": "Case Western is research-intensive and strong in engineering, the sciences, and pre-med, and it weighs demonstrated interest. It offers strong ED options and reads for genuine fit with your intended field. Real research or technical engagement, and a specific reason for Case (its co-op, its labs, the Cleveland medical ecosystem), read well.",
        "acceptedPattern": "Admits show strong academics with genuine STEM depth or research and clear demonstrated interest; fit with the intended program and a specific reason for Case recur, and applying ED helps for a committed applicant."
    },
    {
        "name": "University of Maryland, College Park",
        "aka": [
            "maryland",
            "umd",
            "university of maryland",
            "umcp",
            "maryland college park"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~45% overall (far lower for CS/engineering)",
        "region": "College Park, MD",
        "dataDepth": "deep",
        "motto": "Historically Latin; the university today rallies around \"Fear the Turtle\" and a 'Fearless Ideas' innovation identity. A public flagship near DC.",
        "values": [
            "fit with the major",
            "innovation and initiative",
            "a clear direction",
            "academic rigor"
        ],
        "guidance": "Maryland is a public flagship near DC, very strong in computer science, engineering, and business - and those top majors (plus the honors programs like ACES, QUEST, and the Banneker/Key scholarship) are far more competitive than the ~45% overall rate. It reads for rigor and a clear direction; demonstrated depth in your intended field helps most for the competitive majors. Apply early - Maryland reviews on a priority timeline.",
        "acceptedPattern": "Admits to CS/engineering show genuine technical depth beyond grades; across the board, a clear academic direction and real initiative recur, with honors and top majors rewarding demonstrated depth. Meeting the priority deadline matters."
    },
    {
        "name": "Ohio State University",
        "aka": [
            "ohio state",
            "osu",
            "the ohio state university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~53%",
        "region": "Columbus, OH",
        "dataDepth": "deep",
        "motto": "\"Disciplina in civitatem\" — \"Education for citizenship.\" A very large public flagship strong across many fields.",
        "values": [
            "academic rigor",
            "a clear direction",
            "involvement",
            "fit with the major/honors"
        ],
        "guidance": "Ohio State is a large public flagship, strong across many disciplines, with a competitive Honors & Scholars program and more selective top majors. A solid academic record, a clear direction, and genuine involvement read well; the honors program and standout majors (business, engineering) ask for more. Applying by the early-action deadline improves scholarship and honors consideration.",
        "acceptedPattern": "Admits clear a solid GPA and course-rigor bar with a clear academic direction; the Honors & Scholars program and top majors reward demonstrated depth and involvement. Applying early helps for merit and honors."
    },
    {
        "name": "Texas A&M University",
        "aka": [
            "texas a&m",
            "tamu",
            "aggies",
            "texas am",
            "texas a and m"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~57% overall (holistic for non-auto-admits)",
        "region": "College Station, TX",
        "dataDepth": "deep",
        "motto": "A land-grant flagship defined by the Aggie Core Values (respect, excellence, leadership, loyalty, integrity, selfless service) and a famously tight alumni culture.",
        "values": [
            "character and Core Values",
            "leadership and service",
            "fit with the specific major",
            "a genuine 'why A&M'"
        ],
        "guidance": "Texas A&M has two paths: Texas residents in the top 10% get automatic admission; everyone else (and most out-of-state applicants) goes through full holistic review. Its essay set is distinctive - a 750-word 'Tell us your story' plus short answers including 'why your major' and 'why A&M' - and it reads for the Aggie Core Values, leadership, and service, not just stats. Engineering is a separate, harder holistic review (CS targets ~3.75 GPA via the ETAM process). Apply early (opens in August) and show genuine fit with its strong, service-oriented culture.",
        "acceptedPattern": "Over 40% of admits were NOT top-10%, so holistic factors genuinely matter: admits show rigor plus real leadership, service, and character consistent with the Core Values, and essays with genuine interest in A&M and their specific major/college. Applying early and demonstrated interest recur; engineering/CS admits show serious major-specific depth."
    },
    {
        "name": "University of Georgia (UGA)",
        "aka": [
            "uga",
            "university of georgia",
            "georgia bulldogs"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~37%",
        "region": "Athens, GA",
        "dataDepth": "deep",
        "motto": "\"Et docere et rerum exquirere causas\" — \"To teach and to inquire into the nature of things.\" The oldest state-chartered US university, with standout business and journalism.",
        "values": [
            "academic rigor",
            "genuine involvement and leadership",
            "a clear direction",
            "contribution"
        ],
        "guidance": "UGA is a strong public flagship that reads GPA and course rigor heavily in a first academic read, then weighs essays, involvement, and leadership for many applicants in a holistic second read. Early Action is non-binding and strategically valuable (better odds and scholarship consideration). Its standout Terry business and Grady journalism programs, and the Honors Program, are more competitive. Show rigor plus genuine, sustained involvement.",
        "acceptedPattern": "Admits show strong academics with genuine leadership and sustained involvement; the recurring signal is real contribution over a scattered list. Applying Early Action and demonstrated depth (especially for Terry/Grady/Honors) recur among competitive admits."
    },
    {
        "name": "College of William & Mary",
        "aka": [
            "william and mary",
            "william & mary",
            "w&m",
            "wm"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~33%",
        "region": "Williamsburg, VA",
        "dataDepth": "deep",
        "motto": "A historic public 'Public Ivy' (the second-oldest US college), known for close undergraduate teaching, strong writing, and a liberal-arts ethos.",
        "values": [
            "genuine intellectual engagement",
            "strong writing and voice",
            "fit with a small, close community",
            "academic rigor"
        ],
        "guidance": "William & Mary practices genuine holistic review - every application is read at least twice, including by your regional counselor - and it's test-optional. It's a small, teaching-focused Public Ivy that values intellectual engagement and strong writing, so its essays (including distinctive optional prompts) genuinely matter. Out-of-state admission is notably more competitive. Show authentic voice and how you'd engage a close academic community.",
        "acceptedPattern": "Admits show academic strength plus genuine intellectual engagement and distinctive, well-written essays - W&M explicitly looks for 'dynamic, diverse, academically engaged' students, and voice and fit recur over pure stats, especially for the competitive out-of-state pool."
    },
    {
        "name": "University of Pittsburgh",
        "aka": [
            "pitt",
            "university of pittsburgh",
            "upitt"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~58%",
        "region": "Pittsburgh, PA",
        "dataDepth": "deep",
        "motto": "\"Veritas et Virtus\" — \"Truth and Virtue.\" A public research university strong in the health sciences, engineering, and philosophy.",
        "values": [
            "academic rigor",
            "a clear direction",
            "real-world engagement",
            "applying early"
        ],
        "guidance": "Pitt uses ROLLING admission - there's no set deadline and it reviews files daily starting in August, so applying early is the single biggest strategic lever (better odds plus scholarship, Frederick Honors, and guaranteed-program consideration; decisions come in ~6-8 weeks). It requires the SRAR (self-reported academic record). It reads holistically for rigor and fit, and is strong in the health sciences, engineering, and philosophy. Keep senior-year rigor up.",
        "acceptedPattern": "Admits show solid-to-strong academics and a clear direction; because admission is rolling, applying early genuinely improves outcomes for both admission and honors/scholarships. Demonstrated fit with the intended field recurs."
    },
    {
        "name": "Rutgers University-New Brunswick",
        "aka": [
            "rutgers",
            "rutgers university",
            "ru",
            "rutgers new brunswick"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~66%",
        "region": "New Brunswick, NJ",
        "dataDepth": "deep",
        "motto": "\"Sol iustitiae et occidentem illustra\" — \"Sun of righteousness, shine also upon the West.\" A colonial-era public flagship, strong in many fields, admitting by school.",
        "values": [
            "academic rigor",
            "a clear direction",
            "fit with the school/major",
            "involvement"
        ],
        "guidance": "Rutgers-New Brunswick admits BY school/college (e.g. the School of Arts and Sciences, Engineering, Business), and it's more numbers-driven than the most selective privates - GPA and course rigor carry a lot of weight, and it's largely test-optional. Honors College and top majors are more holistic and competitive. A solid record, clear academic direction, and fit with your chosen school read well.",
        "acceptedPattern": "Admits generally clear a GPA/rigor bar with a clear direction that matches their chosen school; the Honors College and competitive majors (engineering, business) reward additional demonstrated depth. Applying early in the cycle helps."
    },
    {
        "name": "University of Minnesota Twin Cities",
        "aka": [
            "minnesota",
            "umn",
            "university of minnesota",
            "u of m",
            "umn twin cities"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~70%",
        "region": "Minneapolis, MN",
        "dataDepth": "deep",
        "motto": "\"Commune vinculum omnibus artibus\" — \"A common bond for all the arts.\" A large public research flagship strong across many fields.",
        "values": [
            "academic rigor",
            "a clear direction",
            "involvement",
            "fit with the college/major"
        ],
        "guidance": "Minnesota is a large public research flagship, strong across many fields, admitting into specific colleges, with a competitive University Honors Program and more selective top majors (e.g. Carlson business, CSE engineering/CS). It reads for rigor and a clear direction; a solid record with genuine involvement reads well, and honors/top majors ask for more demonstrated depth. Priority deadlines help for scholarships and honors.",
        "acceptedPattern": "Admits clear a solid academic bar with a clear direction that fits their chosen college; the Honors Program and top majors reward demonstrated depth. Meeting the priority deadline recurs among competitive/honors admits."
    },
    {
        "name": "Indiana University Bloomington",
        "aka": [
            "indiana",
            "iu",
            "indiana university",
            "iub",
            "iu bloomington"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~80%",
        "region": "Bloomington, IN",
        "dataDepth": "deep",
        "motto": "\"Lux et Veritas\" — \"Light and Truth.\" A large public flagship famed for the Kelley School of Business, music (Jacobs), and informatics.",
        "values": [
            "academic rigor",
            "fit with the program (esp. direct-admit)",
            "a clear direction",
            "involvement"
        ],
        "guidance": "Indiana is an accessible large flagship overall, but its standout programs are the real story - the Kelley School of Business offers competitive DIRECT ADMIT (far harder than the overall rate; standard admits must later apply to Kelley internally), and the Jacobs School of Music requires auditions. Applying early (Kelley's direct-admit deadline is early) and showing genuine, specific interest and rigor in your target program matters most.",
        "acceptedPattern": "For accessible majors, a solid record suffices; for Kelley direct admit, Jacobs music, and honors, admits show serious program-specific strength (strong quantitative record for Kelley, auditions for Jacobs) and clear demonstrated interest. Applying early for direct admit recurs."
    },
    {
        "name": "Villanova University",
        "aka": [
            "villanova",
            "nova",
            "villanova university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~23%",
        "region": "Villanova, PA",
        "dataDepth": "deep",
        "motto": "\"Veritas, Unitas, Caritas\" — \"Truth, Unity, Love.\" An Augustinian Catholic university with a strong community ethos and standout business and engineering.",
        "values": [
            "character and service",
            "community and 'why Villanova'",
            "a clear purpose",
            "academic strength"
        ],
        "guidance": "Villanova is Augustinian Catholic with a genuinely strong community and service culture, and it weighs fit and demonstrated interest. Its supplemental essays lean toward community, values, and service, so answer them with real reflection and a specific reason for Villanova. Its business (VSB) and engineering programs are more competitive. Consider Early Decision if it's a true first choice.",
        "acceptedPattern": "Admits show strong academics plus genuine service and community involvement, and essays that convey real fit with Villanova's values-driven community. Character, a specific 'why Villanova,' and (for VSB/engineering) demonstrated depth recur."
    },
    {
        "name": "Lehigh University",
        "aka": [
            "lehigh",
            "lehigh university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~29%",
        "region": "Bethlehem, PA",
        "dataDepth": "deep",
        "motto": "\"Homo minister et interpres naturae\" — \"Man, the servant and interpreter of nature.\" Strong in engineering, business, and the integrated sciences.",
        "values": [
            "fit with the college",
            "demonstrated interest",
            "a clear direction",
            "academic rigor"
        ],
        "guidance": "Lehigh admits with attention to fit with its specific colleges (Engineering, Business, Arts & Sciences, and the integrated programs), and it weighs demonstrated interest. It offers strong Early Decision options (ED meaningfully boosts odds). A clear 'why Lehigh,' genuine interest in your intended college, and real academic focus read well.",
        "acceptedPattern": "Admits show strong academics with demonstrated interest and a clear fit with a specific college; applying ED for a committed applicant and genuine engagement with the intended program recur."
    },
    {
        "name": "Brandeis University",
        "aka": [
            "brandeis",
            "brandeis university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~39%",
        "region": "Waltham, MA",
        "dataDepth": "deep",
        "motto": "\"Truth, even unto its innermost parts\" (Emet). A research university founded on a strong social-justice and intellectual tradition.",
        "values": [
            "intellectual seriousness",
            "social justice and service",
            "a distinctive voice",
            "academic depth"
        ],
        "guidance": "Brandeis has a strong intellectual and social-justice tradition (founded in 1948 on inclusive, justice-oriented values) and reads for genuine ideas, values, and academic seriousness. It's test-optional and its essays reward a distinctive voice and real engagement with issues you care about. Show intellectual depth and authentic values fit rather than a generic strong-student profile.",
        "acceptedPattern": "Admits show intellectual seriousness and often a social-justice or service dimension, plus a distinctive, sincere voice; depth and genuine values fit recur over pure stats."
    },
    {
        "name": "University of Miami",
        "aka": [
            "miami",
            "um",
            "university of miami",
            "the u",
            "umiami"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~19%",
        "region": "Coral Gables, FL",
        "dataDepth": "deep",
        "motto": "\"Magna est veritas\" — \"Great is truth.\" A private research university strong in marine science, medicine, business, and music (Frost).",
        "values": [
            "demonstrated interest",
            "a specific 'why Miami'",
            "intellectual vitality / a spike",
            "academic rigor"
        ],
        "guidance": "University of Miami has become notably more selective and weighs demonstrated interest ('considered') - engage genuinely (sessions, campus, opening emails). It does NOT interview, so your personality must come through the Common App and supplemental essays, which should show specific knowledge of Miami's programs, faculty, or opportunities (marine science, the Frost music school, medicine). It values intellectual vitality - a real spike or independent project stands out. Over 60% of admits were top-10% in class.",
        "acceptedPattern": "Admits show strong academics (weighted GPAs well above 3.5, most top-10%) plus a specific, informed reason for Miami and often a developed 'spike.' Generic supplements are easy to spot; specificity and demonstrated interest recur among admits."
    },
    {
        "name": "Fordham University",
        "aka": [
            "fordham",
            "fordham university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~47%",
        "region": "New York City, NY",
        "dataDepth": "deep",
        "motto": "A Jesuit university whose ethos is 'cura personalis' (care for the whole person) and 'New York is my campus, Fordham is my school.'",
        "values": [
            "service and 'men and women for others'",
            "fit with NYC and Fordham",
            "reflection and character",
            "a specific 'why Fordham'"
        ],
        "guidance": "Fordham is Jesuit, and its supplements are explicitly values-oriented - one asks how you'd contribute as an engaged learner and leader drawing on your identity and experiences, another asks about embracing NYC as your campus. Answer with genuine reflection and service; you needn't be Catholic, but alignment with Jesuit values (justice, compassion, service to others) strengthens your case. Applying Early Decision meaningfully boosts odds (ED ~52%). Show a real reason for Fordham and New York specifically.",
        "acceptedPattern": "Admits show solid academics (GPAs above ~3.6, rigorous curriculum) plus genuine service, moral reflection, and a specific connection to Fordham's Jesuit mission and NYC setting. Reflection, character, and a real 'why Fordham' recur; ED applicants have a notable edge."
    },
    {
        "name": "Southern Methodist University (SMU)",
        "aka": [
            "smu",
            "southern methodist",
            "southern methodist university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~47%",
        "region": "Dallas, TX",
        "dataDepth": "deep",
        "motto": "\"Veritas Liberabit Vos\" — \"The truth will make you free.\" Strong in business (Cox) and the arts, with a powerful Dallas alumni and internship network.",
        "values": [
            "fit with a specific school",
            "a clear 'why SMU'",
            "leadership and involvement",
            "demonstrated interest"
        ],
        "guidance": "SMU is a private university strong in business (Cox) and the arts, with deep Dallas corporate connections. It reads for academic strength, fit with its specific schools, and demonstrated interest. A clear, specific reason for SMU (its programs, Dallas opportunities, leadership community) and genuine involvement read well; ED is available for committed applicants.",
        "acceptedPattern": "Admits show solid-to-strong academics and a specific reason for SMU and their intended school, plus genuine leadership/involvement; fit and demonstrated interest recur. Cox business and the arts programs are more competitive."
    },
    {
        "name": "Texas Christian University (TCU)",
        "aka": [
            "tcu",
            "texas christian",
            "texas christian university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~44%",
        "region": "Fort Worth, TX",
        "dataDepth": "deep",
        "motto": "\"Add value; be a good citizen.\" A private university (Disciples of Christ heritage) with a strong community culture and standout Neeley business program.",
        "values": [
            "genuine fit and 'why TCU'",
            "community contribution",
            "character and involvement",
            "academic rigor"
        ],
        "guidance": "TCU places significant weight on essays and fit - it explicitly says 'generic essays do not work here' and values students who articulate clear goals and how they'd contribute to the TCU community. It's test-optional (about half of admits submit scores) and reads course rigor heavily (admitted weighted GPA near ~3.85). Its Neeley School of Business is a top-30 undergraduate program and more competitive. Show genuine, specific interest in TCU's community.",
        "acceptedPattern": "Admits show strong academics with a rigorous curriculum plus essays that convey a genuine, specific reason for TCU and how they'd contribute to its community. Fit, character, and a non-generic 'why TCU' recur; Neeley is more competitive."
    },
    {
        "name": "Baylor University",
        "aka": [
            "baylor",
            "baylor university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~45%",
        "region": "Waco, TX",
        "dataDepth": "deep",
        "motto": "\"Pro Ecclesia, Pro Texana\" — \"For Church, For Texas.\" The largest Baptist university, strong in the sciences, business, and pre-health, with a faith-informed community.",
        "values": [
            "character and faith/values fit",
            "academic rigor",
            "service",
            "a clear direction"
        ],
        "guidance": "Baylor is a large Baptist university with a genuine faith-informed community and mission, strong in the sciences, business, and pre-health. It reads for academic rigor plus character and fit with its values-driven, service-oriented culture. A clear academic direction and authentic engagement with its community and mission read well; honors and top programs are more competitive.",
        "acceptedPattern": "Admits show solid-to-strong academics with a clear direction, plus character and genuine fit with Baylor's faith-informed, service-oriented community. Honors College and competitive majors reward additional demonstrated depth."
    },
    {
        "name": "Syracuse University",
        "aka": [
            "syracuse",
            "cuse",
            "syracuse university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~46% overall (far lower for Newhouse)",
        "region": "Syracuse, NY",
        "dataDepth": "deep",
        "motto": "\"Suos cultores scientia coronat\" — \"Knowledge crowns those who seek her.\" Home to the elite Newhouse communications school and the #1-ranked Maxwell public-affairs program.",
        "values": [
            "fit with a specific school",
            "a distinctive talent or portfolio",
            "demonstrated interest",
            "a clear direction"
        ],
        "guidance": "Syracuse's ~46% overall rate hides that its signature schools are far more competitive - the Newhouse School of Public Communications is often cited at ~8-20%, and Maxwell (public affairs), architecture, and Visual & Performing Arts are standouts (some requiring portfolios/auditions). Admission is school-specific, so a distinctive talent and a clear, specific reason for your Syracuse school matter most. Strong admits average ~3.9 GPA.",
        "acceptedPattern": "For the signature schools, admits show a developed talent or portfolio and clear fit with that specific program; across the board, a clear direction and demonstrated interest recur. Newhouse/architecture/VPA admits show genuine, specific creative or communications depth."
    },
    {
        "name": "Pennsylvania State University (Penn State)",
        "aka": [
            "penn state",
            "psu",
            "pennsylvania state university",
            "penn state university park"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~55%",
        "region": "University Park, PA",
        "dataDepth": "deep",
        "motto": "\"Making Life Better.\" A large public flagship strong in engineering, business (Smeal), and the sciences, with a vast alumni network.",
        "values": [
            "academic rigor",
            "a clear direction",
            "involvement",
            "fit with the major/honors"
        ],
        "guidance": "Penn State is a large public flagship, strong in engineering, business, and the sciences, with more selective top majors and the highly competitive Schreyer Honors College (which has its own essays and a much lower admit rate). It reviews on a rolling-ish priority basis, so applying by the November 30 priority deadline genuinely helps. A solid record, clear direction, and genuine involvement read well; honors and top majors ask for more.",
        "acceptedPattern": "Admits clear a solid academic bar with a clear direction; Schreyer Honors and top majors (engineering, Smeal business) reward demonstrated depth. Applying by the priority deadline recurs among competitive and honors admits."
    },
    {
        "name": "University of Connecticut (UConn)",
        "aka": [
            "uconn",
            "university of connecticut",
            "u conn"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~55%",
        "region": "Storrs, CT",
        "dataDepth": "deep",
        "motto": "\"Qui transtulit sustinet\" — \"He who transplanted still sustains.\" A public flagship strong in the sciences, engineering, business, and nursing.",
        "values": [
            "academic rigor",
            "a clear direction",
            "involvement",
            "fit with the major/honors"
        ],
        "guidance": "UConn is a public flagship strong in the sciences, engineering, business, and nursing, with a competitive Honors Program and more selective top majors. It reads for rigor and a clear direction; a solid academic record with genuine involvement reads well, and honors/top majors ask for more demonstrated depth. Applying by the priority deadline helps for honors and merit.",
        "acceptedPattern": "Admits show solid academics and a clear direction; the Honors Program and competitive majors reward demonstrated depth. Meeting the priority deadline recurs among honors/merit admits."
    },
    {
        "name": "Pepperdine University",
        "aka": [
            "pepperdine",
            "pepperdine university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~49%",
        "region": "Malibu, CA",
        "dataDepth": "deep",
        "motto": "\"Freely ye received, freely give.\" A Christian university (Churches of Christ heritage) with a strong values, service, and global-programs emphasis.",
        "values": [
            "character and faith/values fit",
            "service",
            "a clear purpose",
            "a specific 'why Pepperdine'"
        ],
        "guidance": "Pepperdine is a Christian university with a genuinely strong values, service, and community emphasis and standout study-abroad programs. It reads for character and a reflective sense of purpose alongside academics; its supplements lean toward values, service, and fit. Authentic service and a specific reason for Pepperdine's mission and community read well.",
        "acceptedPattern": "Admits show solid academics plus genuine service and a values-driven purpose, with essays conveying real fit with Pepperdine's Christian, service-oriented mission. Character and a specific 'why Pepperdine' recur."
    },
    {
        "name": "Williams College",
        "aka": [
            "williams",
            "williams college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~9%",
        "region": "Williamstown, MA",
        "dataDepth": "deep",
        "motto": "The top-ranked US liberal arts college, defined by its Oxford-style tutorial system and a rural, undergraduate-centered, scholar-athlete culture.",
        "values": [
            "fit with the tutorial system",
            "intellectual specificity",
            "fit with a small rural community",
            "genuine (not generic) 'why Williams'"
        ],
        "guidance": "Williams is a liberal arts college (~2,000 students) as selective as the Ivies - it rejects many valedictorians. Its defining feature is the TUTORIAL system: Oxford-style classes of just two students who produce and critique work weekly. Its 'Why Williams' supplement should engage the tutorial specifically - readers instantly detect essays that treat Williams as interchangeable with Amherst/Swarthmore/Bowdoin. Fit with the rural Williamstown setting matters (urban-career emphasis signals poor fit). ED is meaningful (~27%) but only works with authentic commitment.",
        "acceptedPattern": "Admits show intellectual specificity and genuine fit with the tutorial format and rural setting; the strongest non-athlete essays focus on academic/intellectual specifics (not athletics), while athlete essays keep sports brief within a broader academic narrative. Generic 'elite LAC' essays and poor rural fit are the top failure modes."
    },
    {
        "name": "Amherst College",
        "aka": [
            "amherst",
            "amherst college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~9%",
        "region": "Amherst, MA",
        "dataDepth": "deep",
        "motto": "\"Terras Irradient\" — \"Let them illuminate the lands.\" A top LAC defined by its open curriculum (no core requirements) and Five College consortium access.",
        "values": [
            "intellectual flexibility and self-direction",
            "fit with the open curriculum",
            "a distinctive voice",
            "genuine curiosity"
        ],
        "guidance": "Amherst is a top liberal arts college (~1,900 students) whose signature is the OPEN CURRICULUM - no general-education requirements, so it seeks intellectually flexible, self-directed students who will make thoughtful choices with that freedom. Its distinctive supplement often asks you to respond to a quotation, rewarding genuine intellectual engagement over polish. Fit with the open curriculum and Five College consortium, plus a distinctive voice, matter more than a broad resume.",
        "acceptedPattern": "Admits show genuine intellectual curiosity and self-direction plus a distinctive voice in the quotation-response essay; a convincing sense of how they'd use curricular freedom recurs. Like all top LACs, generic 'why Amherst' essays fare poorly."
    },
    {
        "name": "Swarthmore College",
        "aka": [
            "swarthmore",
            "swat",
            "swarthmore college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~7%",
        "region": "Swarthmore, PA",
        "dataDepth": "deep",
        "motto": "\"Mind the light\" (a Quaker phrase). An intensely academic LAC with a discussion-based, intellectually rigorous culture and a Quaker ethic of social responsibility.",
        "values": [
            "intellectual intensity",
            "discussion-based rigor",
            "social responsibility",
            "genuine love of ideas"
        ],
        "guidance": "Swarthmore is among the most academically intense liberal arts colleges (~1,700 students), with a discussion-heavy, seminar-driven culture and a Quaker-rooted ethic of social responsibility (its Honors Program uses external examiners, modeled on Oxford). It reads for genuine intellectual intensity and love of ideas, plus a values dimension. Show real depth of thought and how you'd engage its rigorous, discussion-based, ethically-minded community.",
        "acceptedPattern": "Admits show genuine intellectual intensity and a love of ideas for their own sake, often paired with social conscience; the recurring signal is depth of thought and fit with a demanding, discussion-based culture rather than credentials alone."
    },
    {
        "name": "Pomona College",
        "aka": [
            "pomona",
            "pomona college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~7%",
        "region": "Claremont, CA",
        "dataDepth": "deep",
        "motto": "A top LAC and the founding member of the Claremont Colleges consortium, combining a small close-knit college with access to five neighboring campuses.",
        "values": [
            "intellectual curiosity",
            "fit with the consortium model",
            "a distinctive voice",
            "collaboration and community"
        ],
        "guidance": "Pomona is a top liberal arts college (~1,700 students) and the anchor of the Claremont Colleges consortium - you get a small, close college plus cross-registration across five campuses. It reads for intellectual curiosity, character, and genuine fit with its collaborative, sunny, close-knit community. Its supplements reward authentic voice and specificity about Pomona and the consortium. Show real curiosity and how you'd contribute to a tight community.",
        "acceptedPattern": "Admits show genuine curiosity and a distinctive, sincere voice, plus a specific sense of how they'd use the consortium and contribute to Pomona's community; fit and character recur over pure stats."
    },
    {
        "name": "Wellesley College",
        "aka": [
            "wellesley",
            "wellesley college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~13%",
        "region": "Wellesley, MA",
        "dataDepth": "deep",
        "motto": "\"Non Ministrari sed Ministrare\" — \"Not to be ministered unto, but to minister.\" The top women's liberal arts college, with a strong ethic of women's leadership.",
        "values": [
            "women's leadership and empowerment",
            "intellectual rigor",
            "service and contribution",
            "a distinctive voice"
        ],
        "guidance": "Wellesley is the leading women's liberal arts college (~2,400 students), with a powerful legacy of women's leadership (its alumnae include many trailblazers). It reads for intellectual rigor plus a genuine commitment to leadership and making a difference, consistent with its 'not to be ministered unto, but to minister' motto. Its supplement asks why a women's college; answer authentically. Show real academic drive and how you'd contribute to and grow within its community.",
        "acceptedPattern": "Admits show intellectual rigor plus a genuine drive to lead and contribute, and an authentic reason for choosing a women's college. Leadership potential and a distinctive voice recur alongside strong academics."
    },
    {
        "name": "Bowdoin College",
        "aka": [
            "bowdoin",
            "bowdoin college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~9%",
        "region": "Brunswick, ME",
        "dataDepth": "deep",
        "motto": "\"The Offer of the College\" (1906) frames its values: to be at home in all lands and ages, to lose yourself in generous enthusiasms, and to count nature a familiar acquaintance.",
        "values": [
            "character and 'The Offer' values",
            "intellectual engagement",
            "service and community",
            "fit with a close community"
        ],
        "guidance": "Bowdoin is a top liberal arts college (~1,800 students) in coastal Maine, and a test-optional pioneer (since 1969). Its distinctive optional supplement invites you to reflect on a line from 'The Offer of the College' - a genuine window into whether its values resonate with you, so answer it sincerely if it does. It has a strong College House residential system and community ethos. Show character, intellectual engagement, and how you'd contribute to a close community.",
        "acceptedPattern": "Admits show academic strength plus genuine character and community-mindedness, and (when they write it) an authentic response to 'The Offer of the College.' Fit with a close, values-driven community recurs; scores matter less given the long test-optional history."
    },
    {
        "name": "Carleton College",
        "aka": [
            "carleton",
            "carleton college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~17%",
        "region": "Northfield, MN",
        "dataDepth": "deep",
        "motto": "A top Midwestern LAC known for intellectual seriousness worn lightly - a quirky, collaborative, genuinely nerdy-in-the-best-way culture and standout undergraduate teaching.",
        "values": [
            "intellectual curiosity and playfulness",
            "collaboration (not competition)",
            "a distinctive, authentic voice",
            "genuine engagement"
        ],
        "guidance": "Carleton is a top liberal arts college (~2,000 students) in Minnesota, famous for pairing serious academics with a warm, quirky, collaborative (non-cutthroat) culture. Its supplements reward genuine intellectual curiosity and authentic personality - it wants people who love learning and don't take themselves too seriously. Show real curiosity, a distinctive voice, and how you'd add to a collaborative community rather than a polished, generic profile.",
        "acceptedPattern": "Admits show genuine intellectual curiosity and an authentic, often playful voice, plus collaborative spirit; the recurring signal is a real love of learning and fit with Carleton's warm, quirky culture rather than resume polish."
    },
    {
        "name": "Middlebury College",
        "aka": [
            "middlebury",
            "midd",
            "middlebury college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~13%",
        "region": "Middlebury, VT",
        "dataDepth": "deep",
        "motto": "A top LAC renowned for languages (its immersive Language Schools), international studies, and environmental studies, in a rural Vermont setting.",
        "values": [
            "intellectual engagement",
            "fit with its signature strengths (languages/environment/international)",
            "fit with a rural community",
            "a clear direction"
        ],
        "guidance": "Middlebury is a top liberal arts college (~2,900 students) in rural Vermont, world-renowned for language immersion (its summer Language Schools are legendary), international studies, and environmental studies. It reads holistically and its essays reward genuine engagement; fit with the rural setting and its signature academic strengths helps. Show real intellectual interest (especially if it aligns with languages, the environment, or global study) and how you'd engage a close rural community.",
        "acceptedPattern": "Admits show strong academics and genuine intellectual engagement, often with interest in Middlebury's signature areas (languages, international, environmental); fit with a rural, close community and a clear direction recur."
    },
    {
        "name": "Claremont McKenna College",
        "aka": [
            "claremont mckenna",
            "cmc",
            "claremont mckenna college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~10%",
        "region": "Claremont, CA",
        "dataDepth": "deep",
        "motto": "A top LAC focused on 'responsible leadership,' economics, government, and public affairs - pre-professional in flavor and part of the Claremont consortium.",
        "values": [
            "responsible leadership",
            "interest in economics/government/public affairs",
            "real-world application",
            "a specific 'why CMC'"
        ],
        "guidance": "Claremont McKenna is a top liberal arts college (~1,400 students) with a distinctive, pre-professional focus on leadership, economics, government, and public policy - its Athenaeum (a daily speaker/discussion forum) and Robert Day econ/finance program are signatures, and it's part of the Claremont consortium. Its supplements ask directly about 'responsible leadership' and a public-policy issue you care about; answer with genuine specifics and connect your goals to CMC's actual programs (the Athenaeum, research institutes).",
        "acceptedPattern": "Admits show demonstrated leadership and a genuine interest in economics/government/public affairs, plus essays that specifically connect their goals to CMC's programs (Athenaeum, institutes). Specificity and a clear leadership/impact orientation recur."
    },
    {
        "name": "Davidson College",
        "aka": [
            "davidson",
            "davidson college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~17%",
        "region": "Davidson, NC",
        "dataDepth": "deep",
        "motto": "\"Alenda lux ubi orta libertas\" — \"Let learning be cherished where liberty has arisen.\" A top LAC with a rigorous Honor Code and a close, service-minded community.",
        "values": [
            "character and the Honor Code",
            "intellectual rigor",
            "service and community",
            "fit with a close community"
        ],
        "guidance": "Davidson is a top liberal arts college (~2,000 students) near Charlotte, defined by a genuinely central, student-run Honor Code (self-scheduled, unproctored exams) and a strong service ethos. It reads for character, intellectual rigor, and community fit; its essays reward authentic reflection and a real sense of how you'd engage a trust-based, close community. It also meets full demonstrated need. Show integrity, academic seriousness, and community-mindedness.",
        "acceptedPattern": "Admits show strong academics plus genuine character and community engagement consistent with the Honor Code and service culture; integrity, contribution, and fit with a close, trust-based community recur over stats alone."
    },
    {
        "name": "Harvey Mudd College",
        "aka": [
            "harvey mudd",
            "hmc",
            "mudd"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~13%",
        "region": "Claremont, CA",
        "dataDepth": "deep",
        "motto": "A top STEM-focused liberal arts college in the Claremont consortium, uniquely pairing rigorous science/engineering with a required humanities/social-science core and a collaborative (not cutthroat) intensity.",
        "values": [
            "exceptional STEM aptitude",
            "collaboration under intensity",
            "impact and interdisciplinary thinking",
            "authentic voice"
        ],
        "guidance": "Harvey Mudd (~850 students) is a STEM powerhouse LAC whose mission is engineers/scientists/mathematicians who also understand the humanities and 'the impact of their work.' It's academically intense but genuinely collaborative, with a signature Clinic Program (real-world team projects for companies). Its essays ask how your background shapes the problems you want to solve - answer authentically, not with what you think they want. Show exceptional STEM ability plus collaborative spirit and a sense of impact.",
        "acceptedPattern": "Admits show exceptional math/science aptitude AND collaborative character, plus essays connecting their background to real problems they want to solve. The recurring signal is depth in STEM combined with genuine interdisciplinary curiosity and a we-not-me spirit - Mudd is intense but not individualistic."
    },
    {
        "name": "Haverford College",
        "aka": [
            "haverford",
            "haverford college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~14%",
        "region": "Haverford, PA",
        "dataDepth": "deep",
        "motto": "A top LAC defined by its student-run Honor Code (trust-based, self-scheduled exams) and Quaker-rooted values, with Bi-College (Bryn Mawr) and Tri-College/Penn access.",
        "values": [
            "character and the Honor Code",
            "intellectual seriousness",
            "trust and community",
            "originality and careful reading"
        ],
        "guidance": "Haverford (~1,400 students) centers a genuinely student-run Honor Code that shapes academic and social life. Its supplement is famous for a long, values-laden prompt - admissions is testing whether you read carefully AND can push its community values into your own life with originality and honesty. Read it slowly and answer with real reflection. It has Bi-Co (Bryn Mawr) and Tri-Co/Penn consortium access. Show intellectual seriousness, integrity, and genuine fit with a trust-based community.",
        "acceptedPattern": "Admits show intellectual seriousness plus genuine character and honesty consistent with the Honor Code; the recurring signal is a careful, original supplement that applies Haverford's values authentically - generic or careless responses stand out negatively at a school this values-driven."
    },
    {
        "name": "Grinnell College",
        "aka": [
            "grinnell",
            "grinnell college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~11%",
        "region": "Grinnell, IA",
        "dataDepth": "deep",
        "motto": "A top Midwestern LAC with an open curriculum, a strong ethic of self-governance and social justice, and unusually generous financial aid.",
        "values": [
            "intellectual self-direction",
            "social responsibility",
            "self-governance and community",
            "genuine curiosity"
        ],
        "guidance": "Grinnell (~1,700 students) in rural Iowa pairs an OPEN CURRICULUM (design your own course of study via one-on-one academic advising) with a deep culture of self-governance and social justice. It reads for intellectual self-direction, genuine curiosity, and social conscience. Its essays reward authentic engagement with ideas and community. Show that you'd thrive with curricular freedom and contribute to a values-driven, self-governing community - and fit with a rural, close-knit setting.",
        "acceptedPattern": "Admits show genuine intellectual self-direction and a demonstrated commitment to social responsibility; the recurring signal is curiosity plus values and a fit with self-governance, rather than a conventional resume. Grinnell wants students who'll use freedom well and engage a close community."
    },
    {
        "name": "Barnard College",
        "aka": [
            "barnard",
            "barnard college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~7%",
        "region": "New York City, NY",
        "dataDepth": "deep",
        "motto": "A top women's liberal arts college in NYC, partnered with Columbia University - the small-college experience plus access to a research university and the city.",
        "values": [
            "women's leadership and ambition",
            "intellectual boldness",
            "fit with NYC and the Columbia partnership",
            "a distinctive voice"
        ],
        "guidance": "Barnard (~3,000 students) is a women's liberal arts college with a formal partnership with Columbia (shared courses, cross-registration, a Columbia degree affiliation) and all of New York City as its extended campus. It reads for intellectually bold, ambitious women who will use the small-college-plus-research-university-plus-city combination. Its supplements ask why a women's college and why Barnard specifically; answer authentically. Show ambition, a distinctive voice, and genuine fit with its NYC/Columbia context.",
        "acceptedPattern": "Admits show intellectual boldness and ambition plus a genuine reason for choosing a women's college and Barnard's NYC/Columbia setting; a distinctive voice and drive recur alongside strong academics."
    },
    {
        "name": "Wesleyan University",
        "aka": [
            "wesleyan",
            "wesleyan university",
            "wes"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~14%",
        "region": "Middletown, CT",
        "dataDepth": "deep",
        "motto": "An intellectually adventurous LAC known for open curriculum flexibility, strengths in film and the arts, and a progressive, activist campus culture.",
        "values": [
            "intellectual adventurousness",
            "creativity and the arts",
            "independent thinking and activism",
            "a distinctive voice"
        ],
        "guidance": "Wesleyan (~3,000 students) is one of the more intellectually adventurous and creative LACs - flexible curriculum, standout film and arts programs, and a progressive, activist culture. It reads for originality, creativity, and independent thinking, and its essays reward a genuinely distinctive voice over polish. Show intellectual boldness, creative or activist engagement, and how you'd add to a nonconformist community.",
        "acceptedPattern": "Admits show intellectual adventurousness and a distinctive, creative voice, often with artistic or activist depth; the recurring signal is originality and independent thinking rather than a conventional strong-student profile."
    },
    {
        "name": "Hamilton College",
        "aka": [
            "hamilton",
            "hamilton college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~12%",
        "region": "Clinton, NY",
        "dataDepth": "deep",
        "motto": "A top LAC renowned for its open curriculum and an exceptional emphasis on writing and oral communication.",
        "values": [
            "strong writing and communication",
            "intellectual self-direction",
            "fit with the open curriculum",
            "a clear voice"
        ],
        "guidance": "Hamilton (~2,000 students) in rural New York is known for its OPEN CURRICULUM and a distinctive, serious emphasis on writing and speaking (it has a dedicated writing center and communication requirements). It reads for strong writers and self-directed thinkers. Its essays reward clarity and a genuine voice; show that you'd thrive with curricular freedom and value the craft of writing/communication. Fit with a rural, close community helps.",
        "acceptedPattern": "Admits show strong writing and a clear voice plus intellectual self-direction; the recurring signal is genuine engagement with ideas and communication, and fit with the open curriculum, over a broad activity list."
    },
    {
        "name": "Vassar College",
        "aka": [
            "vassar",
            "vassar college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~18%",
        "region": "Poughkeepsie, NY",
        "dataDepth": "deep",
        "motto": "A top LAC (originally a women's college) known for the arts, an open and flexible curriculum, and a creative, independent-minded campus culture.",
        "values": [
            "creativity and the arts",
            "intellectual independence",
            "an open, flexible approach",
            "a distinctive voice"
        ],
        "guidance": "Vassar (~2,400 students) is a creative, intellectually independent LAC with a flexible curriculum and notable strengths in the arts, drama, and film. It reads for originality, genuine intellectual curiosity, and fit with an expressive, open-minded community. Its essays reward a distinctive, authentic voice. Show creative or intellectual depth and how you'd contribute to a nonconformist, arts-friendly community.",
        "acceptedPattern": "Admits show creativity and intellectual independence plus a distinctive voice; the recurring signal is authentic self-expression and genuine curiosity rather than a formulaic profile."
    },
    {
        "name": "Colgate University",
        "aka": [
            "colgate",
            "colgate university"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~12%",
        "region": "Hamilton, NY",
        "dataDepth": "deep",
        "motto": "A top LAC with a strong core/liberal-arts tradition, a beautiful rural campus, and notable strengths in the sciences, economics, and international study.",
        "values": [
            "academic rigor and breadth",
            "genuine 'why Colgate'",
            "involvement and community",
            "fit with a rural campus"
        ],
        "guidance": "Colgate (~3,000 students) is a top LAC in rural New York with a strong liberal-arts core, robust study-abroad, and strengths across the sciences, economics, and international relations. It reads holistically and weighs fit; a specific 'why Colgate' and genuine involvement read well. It offers Early Decision, which helps committed applicants. Show academic rigor, real engagement, and fit with a close, rural campus community.",
        "acceptedPattern": "Admits show strong academics plus genuine involvement and a specific reason for Colgate; fit with a rural, close-knit campus and a clear direction recur, and ED applicants have an edge."
    },
    {
        "name": "Colby College",
        "aka": [
            "colby",
            "colby college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~8%",
        "region": "Waterville, ME",
        "dataDepth": "deep",
        "motto": "A top LAC in Maine known for strong sciences and environmental studies, generous financial aid, and a close, engaged community that has invested heavily in downtown Waterville.",
        "values": [
            "academic rigor",
            "community engagement",
            "fit with a rural/environmental setting",
            "a genuine 'why Colby'"
        ],
        "guidance": "Colby (~2,300 students) is a top LAC in Maine with strengths in the sciences and environmental studies, a January 'Jan Plan' term, and deep community-engagement initiatives (including revitalizing downtown Waterville). It reads holistically and values fit; a specific reason for Colby and genuine engagement read well. It offers Early Decision. Show academic seriousness, community-mindedness, and fit with a close, rural, environmentally-engaged community.",
        "acceptedPattern": "Admits show strong academics plus genuine community engagement and a specific reason for Colby; fit with a close rural community and (often) interest in its science/environmental strengths recur, with an ED edge for committed applicants."
    },
    {
        "name": "Bates College",
        "aka": [
            "bates",
            "bates college"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~14%",
        "region": "Lewiston, ME",
        "dataDepth": "deep",
        "motto": "A top LAC in Maine founded on egalitarian, abolitionist principles (no fraternities, coeducational from the start), test-optional since 1984, with a strong senior-thesis culture.",
        "values": [
            "character and egalitarian values",
            "intellectual engagement",
            "a distinctive voice",
            "community and inclusion"
        ],
        "guidance": "Bates (~1,800 students) is a top LAC in Maine with deep egalitarian roots (founded by abolitionists, coed and fraternity-free from the start) and a pioneering test-optional history (since 1984), so scores carry less weight. It requires a capstone senior thesis and reads for genuine intellectual engagement, character, and inclusive community fit. Its essays reward authentic voice. Show real intellectual curiosity, values alignment, and how you'd contribute to a close, egalitarian community.",
        "acceptedPattern": "Admits show genuine intellectual engagement and character consistent with Bates's egalitarian, inclusive ethos; a distinctive voice and community fit recur, and test scores matter less given the long test-optional history."
    },
    {
        "name": "Smith College",
        "aka": [
            "smith",
            "smith college"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~23%",
        "region": "Northampton, MA",
        "dataDepth": "deep",
        "motto": "The largest of the Seven Sisters women's colleges, with an open curriculum, a strong engineering program (rare for a women's LAC), and a member of the Five College Consortium.",
        "values": [
            "women's leadership",
            "intellectual independence",
            "fit with the open curriculum",
            "a distinctive voice"
        ],
        "guidance": "Smith (~2,500 students) is the largest historically women's college, distinctive for an OPEN CURRICULUM and the first engineering program at a US women's college. It's part of the Five College Consortium (Amherst, Mount Holyoke, Hampshire, UMass). It reads for intellectually independent, ambitious women and rewards a genuine reason for choosing a women's college and Smith specifically. Show academic drive, self-direction with curricular freedom, and how you'd contribute to its community.",
        "acceptedPattern": "Admits show intellectual independence and ambition plus an authentic reason for a women's college; a distinctive voice and drive recur. Interest in its open curriculum, engineering, or consortium access strengthens fit."
    },
    {
        "name": "Mount Holyoke College",
        "aka": [
            "mount holyoke",
            "holyoke",
            "mount holyoke college",
            "mhc"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~38%",
        "region": "South Hadley, MA",
        "dataDepth": "deep",
        "motto": "The oldest of the Seven Sisters (founded 1837), a women's college with a strong global/international student body and Five College Consortium membership.",
        "values": [
            "women's leadership",
            "global perspective",
            "intellectual seriousness",
            "community contribution"
        ],
        "guidance": "Mount Holyoke (~2,200 students) is the oldest women's college in the US, known for a notably international, globally-minded community and Five College Consortium access. It reads for intellectually serious, purpose-driven women and rewards a genuine reason for a women's college. Show academic seriousness, a global or community-minded outlook, and how you'd contribute to and grow within its community.",
        "acceptedPattern": "Admits show intellectual seriousness plus a purpose- or community-minded outlook and an authentic reason for choosing a women's college; a global perspective and genuine contribution recur."
    },
    {
        "name": "Bryn Mawr College",
        "aka": [
            "bryn mawr",
            "bryn mawr college"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~32%",
        "region": "Bryn Mawr, PA",
        "dataDepth": "deep",
        "motto": "\"Veritatem Dilexi\" — \"I have delighted in the truth.\" A Seven Sisters women's college with a rigorous, graduate-serious intellectual culture, a strong Honor Code, and Bi-College (Haverford) / Tri-College (Swarthmore, Penn) access.",
        "values": [
            "intellectual rigor and seriousness",
            "the Honor Code and self-governance",
            "women's scholarship",
            "a distinctive voice"
        ],
        "guidance": "Bryn Mawr (~1,400 students) is a women's college with an unusually rigorous, scholarly culture (it was a pioneer in women's graduate education) and a strong student-run Honor Code and self-governance tradition. It has Bi-Co (Haverford) and Tri-Co (Swarthmore, Penn) consortium access. It reads for genuinely serious intellectuals and rewards depth of thought plus a real reason for a women's college. Show scholarly seriousness, integrity, and fit with a rigorous, self-governing community.",
        "acceptedPattern": "Admits show genuine intellectual rigor and scholarly seriousness plus fit with the Honor Code and self-governance; depth of thought and an authentic reason for a women's college recur over conventional credentials."
    },
    {
        "name": "Colorado College",
        "aka": [
            "colorado college",
            "cc"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~14%",
        "region": "Colorado Springs, CO",
        "dataDepth": "deep",
        "motto": "A top LAC defined by the Block Plan - students take one course at a time, intensively, for three-and-a-half weeks - paired with an outdoorsy, experiential, adventurous culture at the base of Pikes Peak.",
        "values": [
            "intellectual intensity and focus",
            "experiential/adventurous learning",
            "independence and time-management",
            "a genuine 'why the Block Plan'"
        ],
        "guidance": "Colorado College (~2,000 students) is best known for the BLOCK PLAN: one class at a time (9am-noon daily) for 3.5 weeks, eight blocks a year - immersive, intense, and enabling deep fieldwork and outdoor adventure. Its supplements probe fit with this distinctive format, so show that you'd thrive learning one subject intensively and value experiential, focused study. An outdoorsy, adventurous, independent streak fits its culture. Engage the Block Plan specifically, not generically.",
        "acceptedPattern": "Admits show genuine enthusiasm for intensive, immersive learning and fit with the Block Plan's focus and pace, often paired with an adventurous, experiential, or outdoorsy orientation; a specific 'why the Block Plan' recurs over generic LAC essays."
    },
    {
        "name": "Washington and Lee University",
        "aka": [
            "washington and lee",
            "w&l",
            "wlu",
            "washington & lee"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~17%",
        "region": "Lexington, VA",
        "dataDepth": "deep",
        "motto": "\"Non Incautus Futuri\" — \"Not Unmindful of the Future.\" A top LAC with a genuinely central, student-run Honor System and strengths in pre-law, business/commerce, and the humanities.",
        "values": [
            "character and the Honor System",
            "leadership",
            "intellectual seriousness",
            "fit with a close, traditional community"
        ],
        "guidance": "Washington and Lee (~1,800 undergraduates) in Virginia is defined by a deeply central, student-run Honor System (a single-sanction honor code shaping all of campus life) and strengths in pre-law, its Williams School of commerce/economics, and the humanities. It's generous with need- and merit-aid (the Johnson Scholarship). It reads for character, leadership, and intellectual seriousness. Show integrity, leadership, and genuine fit with a close, tradition-minded, honor-based community.",
        "acceptedPattern": "Admits show strong academics plus genuine character and leadership consistent with the Honor System; integrity, contribution, and fit with a close, traditional community recur. The Johnson Scholarship pool is especially competitive."
    },
    {
        "name": "Oberlin College",
        "aka": [
            "oberlin",
            "oberlin college"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~35%",
        "region": "Oberlin, OH",
        "dataDepth": "deep",
        "motto": "\"Learning and Labor.\" A top LAC with a world-class music Conservatory, a pioneering history (first coeducational and among the first to admit Black students), and a deeply progressive, activist culture.",
        "values": [
            "intellectual and artistic passion",
            "social justice and activism",
            "independent thinking",
            "a distinctive voice"
        ],
        "guidance": "Oberlin (~2,900 students, including its renowned Conservatory of Music) has a pioneering, activist identity and a famously progressive, socially-engaged culture. It reads for intellectual and artistic passion, independent thinking, and genuine social conscience. Music applicants apply to the Conservatory (auditions). Its essays reward a distinctive, authentic voice. Show real intellectual or creative depth, values-driven engagement, and fit with a nonconformist, justice-minded community.",
        "acceptedPattern": "Admits show genuine intellectual or artistic passion and often a social-justice orientation, plus a distinctive voice; independent thinking and values fit recur. Conservatory admission hinges on the audition and musical excellence."
    },
    {
        "name": "Kenyon College",
        "aka": [
            "kenyon",
            "kenyon college"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~30%",
        "region": "Gambier, OH",
        "dataDepth": "deep",
        "motto": "A top LAC renowned for English and creative writing (home of the historic Kenyon Review), set on a small, tight-knit rural Ohio campus.",
        "values": [
            "strong writing and a love of literature",
            "intellectual community",
            "a distinctive voice",
            "fit with a rural, close community"
        ],
        "guidance": "Kenyon (~1,800 students) in rural Ohio is famous for English and creative writing (the Kenyon Review is a storied literary journal) and a warm, close intellectual community. It reads for strong writers and genuine humanists, and its essays especially reward voice and craft. Show a real love of ideas and language (whatever your field), a distinctive voice, and fit with a small, rural, tight-knit community.",
        "acceptedPattern": "Admits show strong writing and a genuine love of learning (especially, but not only, in the humanities), plus a distinctive voice; fit with a close, literary, rural community recurs over conventional stats."
    },
    {
        "name": "Macalester College",
        "aka": [
            "macalester",
            "mac",
            "macalester college"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~29%",
        "region": "Saint Paul, MN",
        "dataDepth": "deep",
        "motto": "\"Natura Consilium\" - a top LAC with a defining emphasis on internationalism, multiculturalism, and civic engagement, in the Twin Cities.",
        "values": [
            "global citizenship",
            "service and civic engagement",
            "intellectual seriousness",
            "a distinctive voice"
        ],
        "guidance": "Macalester (~2,100 students) in Saint Paul is distinctive for its core commitments to internationalism, multiculturalism, and service to society - a genuinely globally-minded, civically-engaged community with Twin Cities access. It reads for intellectually serious, globally-aware, service-minded students. Its essays reward authentic engagement with the world and community. Show a global perspective, real civic or service commitment, and intellectual seriousness.",
        "acceptedPattern": "Admits show intellectual seriousness plus genuine global awareness and civic/service engagement, consistent with Macalester's international, service-oriented mission; a distinctive voice and real-world engagement recur."
    },
    {
        "name": "Occidental College",
        "aka": [
            "occidental",
            "oxy",
            "occidental college"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~37%",
        "region": "Los Angeles, CA",
        "dataDepth": "deep",
        "motto": "\"Occidens Proximus Orienti\" - a top LAC in Los Angeles known for interdisciplinary learning, strong civic engagement, and standout programs in politics, international relations, and the arts (with LA as a resource).",
        "values": [
            "civic engagement",
            "interdisciplinary curiosity",
            "fit with an urban LA setting",
            "a distinctive voice"
        ],
        "guidance": "Occidental (~2,000 students) is a top LAC in LA, known for interdisciplinary learning, civic engagement, and strengths in politics and international relations (with real access to Los Angeles's institutions). It reads for intellectually curious, civically-engaged students and rewards genuine fit with an urban, diverse, engaged community. Its essays reward a distinctive voice and specificity about Oxy and LA. Show curiosity, civic-mindedness, and a real reason for Occidental.",
        "acceptedPattern": "Admits show intellectual curiosity and genuine civic engagement plus a specific fit with Oxy's urban, interdisciplinary community; a distinctive voice and clear 'why Oxy/LA' recur."
    },
    {
        "name": "University of Richmond",
        "aka": [
            "richmond",
            "university of richmond",
            "uofr richmond"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~24%",
        "region": "Richmond, VA",
        "dataDepth": "deep",
        "motto": "\"Verbum Vitae et Lumen\" - a top small university blending liberal arts with strong professional schools (business/Robins, leadership studies/Jepson - the nation's first school of leadership studies), with unusually generous aid.",
        "values": [
            "leadership",
            "academic breadth and depth",
            "genuine 'why Richmond'",
            "a distinctive voice"
        ],
        "guidance": "Richmond (~3,000 students) is a small university with a liberal-arts core plus standout professional programs - the Robins School of Business and the Jepson School of Leadership Studies (the first of its kind). It's generous with aid (the Richmond's Promise / merit scholarships). It reads holistically and values fit and demonstrated interest; a specific reason for Richmond and genuine engagement read well. Show academic seriousness, leadership or purpose, and a real 'why Richmond.'",
        "acceptedPattern": "Admits show strong academics plus leadership or clear purpose and a specific reason for Richmond and its distinctive programs; fit and demonstrated interest recur, and the top merit scholarships are especially competitive."
    },
    {
        "name": "University of St Andrews",
        "aka": [
            "st andrews",
            "saint andrews",
            "university of st andrews"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~30-35% offer rate (course-dependent)",
        "region": "St Andrews, Scotland",
        "dataDepth": "deep",
        "motto": "Scotland's first university (founded 1413) and consistently among the very top UK universities, known for a close, traditional community and strong arts, sciences, and international relations.",
        "values": [
            "deep subject knowledge and wider reading",
            "academic independence",
            "a focused personal statement",
            "genuine subject passion"
        ],
        "guidance": "St Andrews (UK course-specific model) values academic, independent, well-read students - its guidance is explicit that grades alone don't guarantee admission, and it weighs your personal statement and reference alongside grades and context. Make the personal statement overwhelmingly about your chosen subject: cite specific wider reading and activities that genuinely deepened your knowledge of it. Most courses decide on grades + PS (no interview, except Medicine, which uses the UCAT and multiple mini-interviews). It pledges offers to UK applicants meeting its criteria.",
        "acceptedPattern": "Successful applicants show demonstrated subject passion beyond the syllabus - specific wider reading, relevant activities, and independent engagement - articulated in a focused personal statement. As across UK admissions, subject depth and academic ability matter far more than a broad activity list."
    },
    {
        "name": "University of Warwick",
        "aka": [
            "warwick",
            "university of warwick"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~60% offer rate overall (far lower for Econ/Maths/CS)",
        "region": "Coventry, England",
        "dataDepth": "deep",
        "motto": "\"Mens agitat molem\" — \"Mind moves matter.\" A leading Russell Group university especially renowned for economics, mathematics (MORSE), business (WBS), and computer science.",
        "values": [
            "exceptional ability in the specific subject",
            "analytical/quantitative strength",
            "a rigorous, specific personal statement",
            "test performance where required"
        ],
        "guidance": "Warwick (UK course-specific model) has a ~60% overall offer rate that badly understates its flagship courses - Economics, Maths, MORSE, and CS require top grades (often A*A*A*) plus admissions tests (TMUA/STEP/MAT for maths-heavy courses), so among near-identical top applicants the personal statement and test performance are the differentiators. Its business school (WMG/WBS) explicitly warns against generic statements ('I want a better job') and inspirational quotes. Make the PS deeply subject-specific and analytical.",
        "acceptedPattern": "For the flagship quantitative courses, admits show top grades, strong admissions-test scores, and a rigorous, subject-specific personal statement demonstrating real analytical engagement. Generic statements and quotes are explicitly penalised; subject depth is everything."
    },
    {
        "name": "Durham University",
        "aka": [
            "durham",
            "durham university"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~40% offer rate (course-dependent)",
        "region": "Durham, England",
        "dataDepth": "deep",
        "motto": "A collegiate Russell Group university (one of England's oldest) with an Oxbridge-adjacent reputation, a strong college system, and standout humanities, sciences, and social sciences.",
        "values": [
            "strong subject ability",
            "a focused personal statement",
            "academic depth beyond the syllabus",
            "fit with the collegiate system"
        ],
        "guidance": "Durham (UK course-specific model) is a collegiate university with a strong academic reputation and, like Oxbridge, a residential college system (you can apply to a specific college or make an open application). Admission is grades + personal statement for most courses (interviews mainly for Medicine/Education); some courses require admissions tests. Make the PS overwhelmingly subject-focused - demonstrated engagement beyond the syllabus. It's a common choice alongside Oxbridge and other top Russell Group universities.",
        "acceptedPattern": "Admits show strong grades and a focused, subject-specific personal statement with genuine engagement beyond the curriculum; as across UK admissions, academic ability and subject depth drive decisions, with the college system a fit/preference layer on top."
    },
    {
        "name": "University of Bristol",
        "aka": [
            "bristol",
            "university of bristol"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~45% offer rate (course-dependent)",
        "region": "Bristol, England",
        "dataDepth": "deep",
        "motto": "\"Vim promovet insitam\" — \"[Learning] promotes one's innate power.\" A leading Russell Group university strong in engineering, medicine, law, and the sciences, with a strong research reputation.",
        "values": [
            "strong subject ability",
            "a skills- and programme-focused personal statement",
            "academic depth",
            "genuine interest in the course"
        ],
        "guidance": "Bristol (UK course-specific model) is a research-intensive Russell Group university that weighs the personal statement heavily and looks for genuine, specific interest in the programme plus relevant skills and academic achievement. Its own guidance emphasises skills, experience, and specific interest in the course. Some courses require admissions tests or extra assessment. Make the PS deeply subject-focused, showing real engagement with your chosen field and why Bristol's course fits.",
        "acceptedPattern": "Admits show strong grades and a personal statement demonstrating genuine, specific interest in the course plus relevant skills and academic depth; subject engagement and course fit recur over breadth, consistent with UK admissions."
    },
    {
        "name": "University of Manchester",
        "aka": [
            "manchester",
            "university of manchester"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~55% offer rate (course-dependent)",
        "region": "Manchester, England",
        "dataDepth": "deep",
        "motto": "\"Cognitio, sapientia, humanitas\" — \"Knowledge, wisdom, humanity.\" A very large Russell Group university with broad strength across the sciences, engineering, medicine, and social sciences.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "academic depth",
            "genuine interest in the course"
        ],
        "guidance": "Manchester (UK course-specific model) is one of the largest Russell Group universities, strong across a very wide range of fields. Admission is grades + personal statement for most courses (some, like Medicine and Dentistry, require admissions tests and interviews). Competitiveness varies substantially by course. Make the personal statement overwhelmingly about your chosen subject - demonstrated engagement and genuine interest in that field.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; competitiveness and any tests vary by course, but academic ability and subject depth are the recurring signals across UK admissions."
    },
    {
        "name": "King's College London (KCL)",
        "aka": [
            "kings college london",
            "kcl",
            "king's college london",
            "kings college"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~40% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "\"Sancte et Sapienter\" — \"With holiness and wisdom.\" A leading Russell Group university in central London, especially strong in medicine, law, humanities, and the health sciences.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "academic depth",
            "genuine interest in the course"
        ],
        "guidance": "King's College London (UK course-specific model) is a research-intensive Russell Group university in central London with particular strength in medicine, dentistry, law, war studies, and the health sciences. Admission is grades + personal statement for most courses; Medicine/Dentistry require the UCAT and interviews. Make the personal statement deeply subject-focused, showing genuine engagement with your chosen field and, where relevant, why King's and London fit.",
        "acceptedPattern": "Admits show strong grades and a subject-focused personal statement with genuine engagement; for the competitive health-science courses, test performance and interviews also matter. Subject depth drives decisions, per UK admissions."
    },
    {
        "name": "University of Bath",
        "aka": [
            "bath",
            "university of bath"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~40% offer rate (course-dependent)",
        "region": "Bath, England",
        "dataDepth": "deep",
        "motto": "\"Generatim discite cultus\" — \"Learn the culture proper to each after its kind.\" A campus university strong in engineering, management, and the sciences, and famous for its placement/sandwich-year programmes.",
        "values": [
            "strong subject ability",
            "interest in professional/placement study",
            "a subject-focused personal statement",
            "academic depth"
        ],
        "guidance": "Bath (UK course-specific model) is a strong campus university especially known for engineering, management (its School of Management is highly rated), and its excellent placement (sandwich-year) programmes with employers. Admission is grades + personal statement; some courses require admissions tests. Because Bath is so placement/career-oriented, showing genuine interest in applying your subject professionally reads well. Keep the PS deeply subject-focused.",
        "acceptedPattern": "Admits show strong grades and a subject-focused personal statement, often with genuine interest in practical/professional application (fitting Bath's placement strength); subject depth and course fit recur, per UK admissions."
    },
    {
        "name": "University of Glasgow",
        "aka": [
            "glasgow",
            "university of glasgow"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~60% offer rate (course-dependent)",
        "region": "Glasgow, Scotland",
        "dataDepth": "deep",
        "motto": "\"Via, Veritas, Vita\" — \"The Way, the Truth, the Life.\" An ancient Russell Group university (founded 1451) with broad strength across medicine, engineering, and the humanities.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "academic depth",
            "genuine interest in the course"
        ],
        "guidance": "Glasgow (UK course-specific model) is an ancient, broad Russell Group university strong across many fields. Admission is grades + personal statement for most courses (Medicine/Dentistry/Vet require tests and interviews); note some Glasgow programmes may not require a personal statement for certain routes. Competitiveness varies by course. Make the personal statement overwhelmingly about your chosen subject and genuine engagement with it.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; competitiveness and any tests vary by course, with academic ability and subject depth the recurring signals per UK admissions."
    },
    {
        "name": "University of Exeter",
        "aka": [
            "exeter",
            "university of exeter"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~60% offer rate (course-dependent)",
        "region": "Exeter, England",
        "dataDepth": "deep",
        "motto": "\"Lucem sequimur\" — \"We follow the light.\" A Russell Group university strong in business, the humanities, and environmental science, with a strong student experience reputation.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Exeter (UK course-specific model) is a Russell Group university strong in business, the humanities, law, and environmental/geographical sciences. Admission is grades + personal statement for most courses (some require admissions tests). Note Exeter is among the Russell Group universities that may not require a personal statement for all programmes - check the specific course. Where it's read, make it deeply subject-focused with genuine engagement.",
        "acceptedPattern": "Admits show the required grades and, where read, a subject-focused personal statement with genuine engagement; academic ability and subject fit recur, per UK admissions. Competitiveness varies by course."
    },
    {
        "name": "University of Leeds",
        "aka": [
            "leeds",
            "university of leeds"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~60% offer rate (course-dependent)",
        "region": "Leeds, England",
        "dataDepth": "deep",
        "motto": "\"Et augebitur scientia\" — \"And knowledge will be increased.\" A large Russell Group university with broad strength across the arts, sciences, engineering, and business.",
        "values": [
            "strong subject ability",
            "a concise, subject-focused personal statement",
            "academic depth",
            "genuine interest in the course"
        ],
        "guidance": "Leeds (UK course-specific model) is a large, broad Russell Group university strong across many fields. Admission is grades + personal statement for most courses (Medicine/Dentistry require tests and interviews). Leeds is notably strict on personal-statement length for some routes (keep it concise and entirely your own work). Make the PS overwhelmingly about your chosen subject and genuine engagement with it.",
        "acceptedPattern": "Admits show the required grades and a concise, subject-focused personal statement with genuine engagement; competitiveness and any tests vary by course, with academic ability and subject depth the recurring signals per UK admissions."
    },
    {
        "name": "University of Nottingham",
        "aka": [
            "nottingham",
            "university of nottingham"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~65-75% offer rate (course-dependent)",
        "region": "Nottingham, England",
        "dataDepth": "deep",
        "motto": "\"Sapientia urbs conditur\" — \"A city is built on wisdom.\" A large, broad Russell Group university strong in medicine, engineering, sciences, and business, with a global reputation.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Nottingham (UK course-specific model) is a broad Russell Group university with a wide range of grade requirements - a few flagship courses ask A*AA, but many are more accessible, and foundation-year routes exist. Admission is grades + personal statement for most courses (Medicine requires the UCAT and interviews). You need at least Grade 4 in English and Maths at GCSE. Make the personal statement overwhelmingly about your chosen subject and genuine engagement with it.",
        "acceptedPattern": "Admits show the required grades (course-dependent) and a subject-focused personal statement with genuine engagement; academic ability and subject depth are the recurring signals per UK admissions, with Medicine and top courses notably more competitive."
    },
    {
        "name": "University of Southampton",
        "aka": [
            "southampton",
            "university of southampton"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~65-75% offer rate (course-dependent)",
        "region": "Southampton, England",
        "dataDepth": "deep",
        "motto": "A Russell Group university with particular strength in engineering (especially aeronautics and maritime), computer science, oceanography, and the sciences.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course (esp. STEM)",
            "academic depth"
        ],
        "guidance": "Southampton (UK course-specific model) is a research-intensive Russell Group university known especially for engineering, computer science, and its world-leading oceanography and maritime research (near the coast). Admission is grades + personal statement for most courses (Medicine requires the UCAT and interview). Make the personal statement deeply subject-focused, showing genuine engagement with your chosen field - particularly valuable for its strong STEM and maritime programmes.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement, often with demonstrated STEM interest for its signature engineering/CS/oceanography courses; academic ability and subject depth recur per UK admissions."
    },
    {
        "name": "University of Sheffield",
        "aka": [
            "sheffield",
            "university of sheffield"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~75-80% offer rate (course-dependent)",
        "region": "Sheffield, England",
        "dataDepth": "deep",
        "motto": "\"Rerum cognoscere causas\" — \"To understand the causes of things.\" A Russell Group university with a strong, welcoming reputation and standout engineering, materials science, and the arts/humanities.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Sheffield (UK course-specific model) is a research-intensive Russell Group university with a notably high offer rate (around 78% in a recent cycle) and standout engineering, materials science, and arts/humanities programmes, plus an excellent Students' Union. Admission is grades + personal statement for most courses (Medicine requires the UCAT and interview). Make the personal statement overwhelmingly about your chosen subject and genuine engagement with it.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; the recurring signal is academic ability and subject depth per UK admissions, with a relatively generous offer rate for many courses."
    },
    {
        "name": "University of Birmingham",
        "aka": [
            "birmingham",
            "university of birmingham",
            "uob"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~65-75% offer rate (course-dependent)",
        "region": "Birmingham, England",
        "dataDepth": "deep",
        "motto": "\"Per Ardua Ad Alta\" — \"Through effort to the heights.\" A large civic Russell Group university (the original 'redbrick') with broad strength across medicine, engineering, business, and the humanities.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Birmingham (UK course-specific model) is a large civic Russell Group university (the first of the 'redbricks') strong across a wide range of fields, with typical offers around AAA-ABB. Admission is grades + personal statement for most courses (Medicine/Dentistry require the UCAT and interviews). Make the personal statement deeply subject-focused, showing genuine engagement with your chosen field.",
        "acceptedPattern": "Admits show the required grades (typically AAA-ABB, course-dependent) and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur per UK admissions."
    },
    {
        "name": "Newcastle University",
        "aka": [
            "newcastle",
            "newcastle university"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "Newcastle upon Tyne, England",
        "dataDepth": "deep",
        "motto": "A civic Russell Group university with some of the more accessible entry requirements in the group, strong in medicine, engineering, and the sciences, and known for generous contextual offers.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Newcastle (UK course-specific model) is a civic Russell Group university with among the more accessible grade requirements in the group (many courses ask ABB), and notably generous contextual offers (which can lower requirements by up to three grades for eligible applicants). Admission is grades + personal statement for most courses; only Medicine and Dentistry use an admissions test (UCAT) and interviews. Make the personal statement subject-focused with genuine engagement.",
        "acceptedPattern": "Admits show the required grades (often ABB, lower with contextual offers) and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur, with contextual offers meaningfully widening access."
    },
    {
        "name": "Cardiff University",
        "aka": [
            "cardiff",
            "cardiff university",
            "prifysgol caerdydd"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~65-75% offer rate (course-dependent)",
        "region": "Cardiff, Wales",
        "dataDepth": "deep",
        "motto": "The sole Welsh member of the Russell Group, strong in medicine, engineering, journalism, and world-leading in brain research (its neuroscience institute).",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Cardiff (UK course-specific model) is the only Welsh Russell Group university, strong in medicine, engineering, journalism, and neuroscience/brain research, with typical offers around AAA-BBB depending on course (CS around ABB/BBB). Admission is grades + personal statement for most courses (Medicine/Dentistry require the UCAT and interviews). Make the personal statement deeply subject-focused, showing genuine engagement with your chosen field.",
        "acceptedPattern": "Admits show the required grades (course-dependent) and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur per UK admissions, with Medicine and top courses more competitive."
    },
    {
        "name": "University of York",
        "aka": [
            "york",
            "university of york"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "York, England",
        "dataDepth": "deep",
        "motto": "A collegiate Russell Group university (a leading 'plate-glass' university) with strong sciences, social sciences, history, and a strong teaching and research reputation.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "York (UK course-specific model) is a collegiate Russell Group university with a strong research and teaching reputation across the sciences, social sciences, and humanities, with typical offers around AAA-BBB. Admission is grades + personal statement for most courses (Medicine requires the UCAT and interview). Make the personal statement overwhelmingly about your chosen subject and genuine engagement with it.",
        "acceptedPattern": "Admits show the required grades (course-dependent) and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur per UK admissions."
    },
    {
        "name": "Queen Mary University of London (QMUL)",
        "aka": [
            "queen mary",
            "qmul",
            "queen mary university of london",
            "queen mary university"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~65-75% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "A Russell Group university in East London, strong in medicine (Barts), law, and the sciences, and known for a diverse, research-intensive community.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Queen Mary (UK course-specific model) is a research-intensive Russell Group university in East London, strong in medicine (its Barts and The London medical school), law, and the sciences, and notably diverse. Admission is grades + personal statement for most courses (Medicine/Dentistry require the UCAT and interviews). Make the personal statement deeply subject-focused, showing genuine engagement with your chosen field.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur per UK admissions, with the Barts medical courses more competitive."
    },
    {
        "name": "Lancaster University",
        "aka": [
            "lancaster",
            "lancaster university"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~65-75% offer rate (course-dependent)",
        "region": "Lancaster, England",
        "dataDepth": "deep",
        "motto": "\"Patet omnibus veritas\" — \"Truth lies open to all.\" A collegiate campus university (not Russell Group but consistently highly ranked), strong in management, physics, and environmental science.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Lancaster (UK course-specific model) is a collegiate campus university that ranks consistently among the UK's best despite not being in the Russell Group - strong in management (its business school is triple-accredited), physics, environmental science, and linguistics. Admission is grades + personal statement, with typical offers around AAA-BBB. Make the personal statement overwhelmingly about your chosen subject and genuine engagement with it.",
        "acceptedPattern": "Admits show the required grades (course-dependent) and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur per UK admissions. A strong reminder that top course quality isn't limited to the Russell Group."
    },
    {
        "name": "Loughborough University",
        "aka": [
            "loughborough",
            "loughborough university",
            "lboro"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~65-75% offer rate (course-dependent)",
        "region": "Loughborough, England",
        "dataDepth": "deep",
        "motto": "\"Veritate, scientia, labore\" — \"With truth, wisdom, and effort.\" A campus university (not Russell Group) world-renowned for sport and exercise science, plus strong engineering, design, and business.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Loughborough (UK course-specific model) is a campus university that, despite not being in the Russell Group, is world-leading in sport and exercise science (consistently #1 globally) and strong in engineering, design, and business, with an outstanding student experience and sports facilities. Admission is grades + personal statement, with typical offers around AAB-ABB. Make the personal statement deeply subject-focused; for sport science and its signature programmes, genuine, specific engagement with the field reads especially well.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; for its world-leading sport-science and engineering/design programmes, demonstrated specific interest recurs. Another reminder that elite course quality extends beyond the Russell Group."
    },
    {
        "name": "University of Liverpool",
        "aka": [
            "liverpool",
            "university of liverpool"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "Liverpool, England",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" A founding civic 'redbrick' Russell Group university, strong in medicine, veterinary science, and engineering.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Liverpool (UK course-specific model) is a founding redbrick Russell Group university, strong in medicine, veterinary science, and engineering, with typical offers around AAA-BBB. Admission is grades + personal statement for most courses (Medicine/Dentistry/Vet require admissions tests and interviews). Make the personal statement deeply subject-focused, showing genuine engagement with your chosen field.",
        "acceptedPattern": "Admits show the required grades (course-dependent) and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur per UK admissions, with Medicine/Vet notably more competitive."
    },
    {
        "name": "Queen's University Belfast (QUB)",
        "aka": [
            "queens university belfast",
            "qub",
            "queen's university belfast",
            "queens belfast"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~30-40% intake (course-dependent)",
        "region": "Belfast, Northern Ireland",
        "dataDepth": "deep",
        "motto": "\"Pro tanto quid retribuamus\" — \"For so much, what shall we give back.\" The sole Northern Irish Russell Group member (joined 2007), strong in dentistry, pharmacy, food science, and law.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Queen's Belfast (UK course-specific model) is the only Northern Irish Russell Group university, a research-intensive institution strong in dentistry, pharmacy, food science, accounting/finance, and law. Admission is grades + personal statement for most courses (Medicine/Dentistry require the UCAT and interviews). It runs a Pathway Opportunity Programme offering contextual offers and guaranteed interviews for eligible students. Make the personal statement subject-focused with genuine engagement.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur per UK admissions, with contextual pathways widening access for eligible applicants."
    },
    {
        "name": "University of Leicester",
        "aka": [
            "leicester",
            "university of leicester"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "Leicester, England",
        "dataDepth": "deep",
        "motto": "\"Ut vitam habeant\" — \"So that they may have life.\" A Russell-adjacent research university (where DNA genetic fingerprinting was invented) with strengths in genetics, space science, and the sciences.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Leicester (UK course-specific model) is a research university famous for pioneering DNA genetic fingerprinting and for space science (it runs a National Space Centre partnership), with strengths across genetics, physics/astronomy, and the sciences, plus notably generous contextual and access provision. Admission is grades + personal statement for most courses (Medicine requires the UCAT and interview). Make the personal statement subject-focused with genuine engagement.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur per UK admissions, with strong access/contextual provision widening entry."
    },
    {
        "name": "University of Surrey",
        "aka": [
            "surrey",
            "university of surrey"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "Guildford, England",
        "dataDepth": "deep",
        "motto": "A campus university (not Russell Group) renowned for its professional placement (sandwich) programmes and strong graduate employability, plus veterinary medicine, engineering, and hospitality.",
        "values": [
            "strong subject ability",
            "interest in placement/professional study",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Surrey (UK course-specific model) is a campus university known for excellent professional placement years (its Professional Training placements are a signature) and strong graduate employability, with well-regarded veterinary medicine, engineering, and hospitality programmes. Admission is grades + personal statement, typical offers around AAB-BBB. Because Surrey is so placement/career-focused, showing genuine interest in applying your subject professionally reads well. Keep the personal statement subject-focused.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement, often with genuine interest in practical/professional application (fitting Surrey's placement strength); subject depth and course fit recur per UK admissions."
    },
    {
        "name": "University of Sussex",
        "aka": [
            "sussex",
            "university of sussex"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "Brighton, England",
        "dataDepth": "deep",
        "motto": "\"Be still and know.\" A campus university (a leading 'plate-glass' university) renowned for development studies (its IDS is world-#1), the social sciences, and a progressive, interdisciplinary ethos.",
        "values": [
            "strong subject ability",
            "interdisciplinary curiosity",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Sussex (UK course-specific model) is a campus university near Brighton, world-leading in development studies (the Institute of Development Studies is consistently ranked #1 globally) and strong in the social sciences, with a progressive, interdisciplinary culture. Admission is grades + personal statement, typical offers around AAB-BBB. Make the personal statement subject-focused with genuine engagement; its social-science and development strengths reward applicants with real interest in those areas.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement, often with interest in the social sciences or development for its signature programmes; subject depth recurs per UK admissions."
    },
    {
        "name": "University of East Anglia (UEA)",
        "aka": [
            "uea",
            "university of east anglia",
            "east anglia"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~75-85% offer rate (course-dependent)",
        "region": "Norwich, England",
        "dataDepth": "deep",
        "motto": "\"Do Different.\" A campus university renowned for creative writing (its MA has produced multiple Booker Prize winners), environmental sciences, and a strong research reputation.",
        "values": [
            "strong subject ability",
            "genuine interest in the course (esp. writing/environment)",
            "a subject-focused personal statement",
            "academic depth"
        ],
        "guidance": "UEA (UK course-specific model) is a campus university in Norwich famous for its creative writing programme (its alumni include Booker Prize winners and it's arguably the UK's most storied writing school) and for world-class environmental sciences and climate research. Admission is grades + personal statement, typical offers around AAB-BBB. Make the personal statement subject-focused with genuine engagement; its writing and environmental programmes reward applicants with real, demonstrated interest.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement, often with demonstrated interest for its signature writing or environmental programmes; subject depth recurs per UK admissions."
    },
    {
        "name": "University of Strathclyde",
        "aka": [
            "strathclyde",
            "university of strathclyde"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "Glasgow, Scotland",
        "dataDepth": "deep",
        "motto": "\"The place of useful learning.\" A technological university in Glasgow strong in engineering, business (its triple-accredited Strathclyde Business School), and the sciences, with a practical, industry-focused ethos.",
        "values": [
            "strong subject ability",
            "practical/applied focus",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Strathclyde (UK course-specific model) is a Glasgow technological university with a genuinely practical, industry-focused mission ('the place of useful learning'), strong in engineering, its triple-accredited business school, and applied sciences. Admission is grades + personal statement (Scottish four-year degree structure). Make the personal statement subject-focused with genuine engagement; its applied, industry-linked programmes reward real interest in practical application.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement, often with a practical/applied orientation fitting its 'useful learning' mission; subject depth recurs per UK admissions."
    },
    {
        "name": "University of Aberdeen",
        "aka": [
            "aberdeen",
            "university of aberdeen"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~75-85% offer rate (course-dependent)",
        "region": "Aberdeen, Scotland",
        "dataDepth": "deep",
        "motto": "\"Initium sapientiae timor domini\" — \"The fear of the Lord is the beginning of wisdom.\" An ancient Scottish university (founded 1495) strong in medicine, law, and energy/geoscience (with North Sea energy links).",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Aberdeen (UK course-specific model) is an ancient Scottish university (the UK's fifth-oldest) strong in medicine, law, divinity, and energy/geoscience (with deep North Sea oil-and-gas and now renewables links). Admission is grades + personal statement (Scottish four-year degrees); Medicine requires the UCAT and interview. Make the personal statement subject-focused with genuine engagement.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; academic ability and subject depth recur per UK admissions, with Medicine more competitive."
    },
    {
        "name": "University of Dundee",
        "aka": [
            "dundee",
            "university of dundee"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~75-85% offer rate (course-dependent)",
        "region": "Dundee, Scotland",
        "dataDepth": "deep",
        "motto": "\"Magnificat anima mea dominum\" — a Scottish university renowned for life sciences (world-leading biomedical research), medicine, dentistry, and art & design (its Duncan of Jordanstone college).",
        "values": [
            "strong subject ability",
            "genuine interest in the course (esp. life sciences/art)",
            "a subject-focused personal statement",
            "academic depth"
        ],
        "guidance": "Dundee (UK course-specific model) is a Scottish university with world-leading life-sciences/biomedical research, strong medicine and dentistry, and a renowned art & design school (Duncan of Jordanstone). Admission is grades + personal statement (Scottish four-year degrees); Medicine/Dentistry require admissions tests and interviews, and art & design routes require a portfolio. Make the personal statement subject-focused; portfolio quality is central for art applicants.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; for its signature life-sciences, medicine, and art & design programmes, demonstrated subject depth (or portfolio, for art) recurs per UK admissions."
    },
    {
        "name": "University of Reading",
        "aka": [
            "reading",
            "university of reading"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~75-85% offer rate (course-dependent)",
        "region": "Reading, England",
        "dataDepth": "deep",
        "motto": "A campus university strong in meteorology (its department is world-#1), agriculture, real estate/land management, and the environmental sciences.",
        "values": [
            "strong subject ability",
            "genuine interest in the course",
            "a subject-focused personal statement",
            "academic depth"
        ],
        "guidance": "Reading (UK course-specific model) is a campus university with genuine world-leading strengths in meteorology/climate science (its department is consistently ranked #1 globally), agriculture, real estate and planning (Henley Business School), and environmental sciences. Admission is grades + personal statement, typical offers around ABB-BBB. Make the personal statement subject-focused with genuine engagement; its signature programmes reward applicants with real, demonstrated interest.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement, often with demonstrated interest for its signature meteorology, agriculture, or real-estate programmes; subject depth recurs per UK admissions."
    },
    {
        "name": "SOAS University of London",
        "aka": [
            "soas",
            "soas university of london",
            "school of oriental and african studies"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "\"Knowledge is power.\" The world's leading specialist institution for the study of Asia, Africa, and the Middle East - languages, politics, development, law, and area studies.",
        "values": [
            "genuine interest in its regional/area-studies focus",
            "a subject-focused personal statement",
            "global and critical perspective",
            "academic depth"
        ],
        "guidance": "SOAS (UK course-specific model) is uniquely specialised in Asian, African, and Middle Eastern studies - languages, development, politics, law, anthropology, and area studies - with a distinctive critical, globally-minded ethos. Admission is grades + personal statement, typically around AAB-BBB. Because it's so specialised, a genuine, specific interest in its regional focus and its critical approach reads especially well. Make the personal statement subject-focused, showing real engagement with the languages, regions, or global issues you want to study.",
        "acceptedPattern": "Admits show genuine, specific interest in SOAS's regional and area-studies focus and a critical global perspective, plus the required grades; the recurring signal is authentic engagement with its distinctive specialism rather than generic strong-student credentials."
    },
    {
        "name": "Royal Holloway, University of London",
        "aka": [
            "royal holloway",
            "rhul",
            "royal holloway university of london"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~75-85% offer rate (course-dependent)",
        "region": "Egham, England",
        "dataDepth": "deep",
        "motto": "\"Esse quam videri\" — \"To be, rather than to seem.\" A University of London college with a landmark Founder's Building, strong in information security (CS), drama, music, and the humanities.",
        "values": [
            "strong subject ability",
            "genuine interest in the course",
            "a subject-focused personal statement",
            "academic depth"
        ],
        "guidance": "Royal Holloway (UK course-specific model) is a University of London college near London, with a benchmark of around AAB and genuine strengths in Information Security within computer science, drama and theatre, music, and the humanities. Admission is grades + personal statement (drama/music routes may involve audition/interview). Make the personal statement subject-focused with genuine engagement; its signature programmes reward demonstrated specific interest.",
        "acceptedPattern": "Admits show the required grades (around AAB, course-dependent) and a subject-focused personal statement with genuine engagement; for its signature information-security, drama, and music programmes, demonstrated specific interest (or audition/portfolio) recurs per UK admissions."
    },
    {
        "name": "City St George's, University of London",
        "aka": [
            "city university london",
            "city st georges",
            "city university of london",
            "city st george's"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "A London university (recently merged with St George's) strong in business (Bayes Business School), journalism, law, and the health sciences, with a professional, career-oriented ethos.",
        "values": [
            "strong subject ability",
            "a career/professional orientation",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "City St George's, University of London (UK course-specific model) is a professionally-oriented London university with standout programmes in business (Bayes Business School), journalism, law, and - since its merger with St George's - the health sciences and medicine. Admission is grades + personal statement (health/medicine routes require tests and interviews). Its career focus means genuine interest in professional application reads well. Make the personal statement subject-focused with real engagement.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement, often with a clear professional or career orientation fitting City's ethos; subject depth and course fit recur per UK admissions."
    },
    {
        "name": "Brunel University of London",
        "aka": [
            "brunel",
            "brunel university",
            "brunel university of london"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~75-85% offer rate (course-dependent)",
        "region": "Uxbridge, England",
        "dataDepth": "deep",
        "motto": "Named after the engineer Isambard Kingdom Brunel, a London campus university strong in engineering, design, and business, with a practical, industry-linked ethos and strong placement provision.",
        "values": [
            "strong subject ability",
            "a practical/applied focus",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Brunel (UK course-specific model) is a London campus university named after the Victorian engineer, with a practical, industry-linked identity and genuine strengths in engineering, design (product/industrial), and business, plus strong placement/sandwich-year provision. Admission is grades + personal statement, typically around ABB-BBB. Its applied focus means genuine interest in practical/professional application reads well. Make the personal statement subject-focused.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement, often with a practical/applied orientation and interest in placements; subject depth and course fit recur per UK admissions."
    },
    {
        "name": "University of Kent",
        "aka": [
            "kent",
            "university of kent"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~80-90% offer rate (course-dependent)",
        "region": "Canterbury, England",
        "dataDepth": "deep",
        "motto": "\"Cui servire regnare est\" - a campus university historically branded 'the UK's European university,' strong in social sciences, arts, humanities, and law, with a collegiate campus near Canterbury.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic depth"
        ],
        "guidance": "Kent (UK course-specific model) is a collegiate campus university near Canterbury, historically known for its European outlook and continental links, strong in the social sciences, humanities, arts, and law. Admission is grades + personal statement, typically around ABB-BBB, with a generous offer rate for many courses. Make the personal statement subject-focused with genuine engagement.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; academic ability and subject fit recur per UK admissions, with a relatively accessible offer rate for many courses."
    },
    {
        "name": "University of Essex",
        "aka": [
            "essex",
            "university of essex"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~80-90% offer rate (course-dependent)",
        "region": "Colchester, England",
        "dataDepth": "deep",
        "motto": "\"Thought the harder, heart the keener.\" A campus university renowned for the social sciences - especially politics, economics, sociology, and human rights - with a strong research and activist tradition.",
        "values": [
            "strong subject ability",
            "genuine interest (esp. social sciences/human rights)",
            "a subject-focused personal statement",
            "academic depth"
        ],
        "guidance": "Essex (UK course-specific model) is a campus university with a genuinely outstanding reputation in the social sciences - politics, economics, sociology - and a distinctive human-rights and activist tradition. Admission is grades + personal statement, typically around ABB-BBB, with a generous offer rate for many courses. Its social-science strengths reward genuine, specific interest. Make the personal statement subject-focused with real engagement.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement, often with demonstrated interest for its signature social-science and human-rights programmes; subject depth recurs per UK admissions, with a relatively accessible offer rate."
    },
    {
        "name": "Aston University",
        "aka": [
            "aston",
            "aston university"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~75-85% offer rate (course-dependent)",
        "region": "Birmingham, England",
        "dataDepth": "deep",
        "motto": "\"Forward.\" A Birmingham city-centre university with a strong professional, placement-focused identity and standout business (Aston Business School), engineering, pharmacy, and optometry.",
        "values": [
            "strong subject ability",
            "a placement/professional orientation",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Aston (UK course-specific model) is a Birmingham university with a strong professional, employability-focused ethos and excellent placement (sandwich-year) provision, with genuine strengths in business (its triple-accredited business school), engineering, pharmacy, and optometry. Admission is grades + personal statement, typically around ABB-BBB. Its career focus means genuine interest in professional application reads well. Keep the personal statement subject-focused.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement, often with a practical/professional orientation fitting Aston's placement strength; subject depth and course fit recur per UK admissions."
    },
    {
        "name": "Heriot-Watt University",
        "aka": [
            "heriot-watt",
            "heriot watt",
            "heriot-watt university"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~75-85% offer rate (course-dependent)",
        "region": "Edinburgh, Scotland",
        "dataDepth": "deep",
        "motto": "\"Leac na fìrinne\" / a technological university (the UK's eighth-oldest) strong in engineering, the built environment, actuarial science, and energy, with global campuses.",
        "values": [
            "strong subject ability",
            "a practical/technical focus",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Heriot-Watt (UK course-specific model) is an Edinburgh technological university with a practical, industry-focused identity and genuine strengths in engineering, the built environment, actuarial mathematics, and energy (with campuses in Dubai and Malaysia too). Its admission is by individual assessment - experience and skills are valued alongside formal qualifications - within the Scottish four-year structure. Make the personal statement subject-focused, showing genuine technical/practical engagement.",
        "acceptedPattern": "Admits show the required qualifications (assessed individually, with skills/experience considered) and a subject-focused personal statement with genuine engagement, often practical/technical; subject depth recurs per UK admissions."
    },
    {
        "name": "University of Stirling",
        "aka": [
            "stirling",
            "university of stirling"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~80-90% offer rate (course-dependent)",
        "region": "Stirling, Scotland",
        "dataDepth": "general",
        "motto": "\"Innovation and excellence\" - a Scottish campus university known for sports studies, aquaculture, education, and a scenic campus, with a flexible, semester-based structure.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic fit"
        ],
        "guidance": "Stirling (UK course-specific model) is a Scottish campus university with recognised strengths in sports studies (it's Scotland's University for Sporting Excellence), aquaculture, education, and the social sciences, on a scenic loch-side campus. Admission is grades + personal statement (Scottish four-year degrees). As with all UK applications, make the personal statement overwhelmingly about your chosen subject and genuine engagement with it. (This entry is source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement showing genuine interest. As across UK admissions, academic fit and subject engagement are what matter; verify exact requirements on the course page."
    },
    {
        "name": "Swansea University",
        "aka": [
            "swansea",
            "swansea university",
            "prifysgol abertawe"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~80-90% offer rate (course-dependent)",
        "region": "Swansea, Wales",
        "dataDepth": "general",
        "motto": "\"Technium\" / a Welsh seaside university strong in engineering, medicine, sports science, and law, known for a beachfront Bay Campus and strong student experience.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic fit"
        ],
        "guidance": "Swansea (UK course-specific model) is a Welsh university with a beachfront campus and genuine strengths in engineering, medicine (graduate-entry), sports science, and law, with a strong student-experience reputation. Admission is grades + personal statement (Medicine routes require tests/interviews). As with all UK applications, make the personal statement overwhelmingly about your chosen subject and genuine engagement with it. (This entry is source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement showing genuine interest; academic fit and subject engagement are the recurring signals across UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Keele University",
        "aka": [
            "keele",
            "keele university"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~80-90% offer rate (course-dependent)",
        "region": "Keele, Staffordshire, England",
        "dataDepth": "deep",
        "motto": "\"Thanke God for all\" - a campus university that pioneered the UK's dual-honours degree system (study two subjects together), on one of the UK's largest parkland campuses, with a strong medical school.",
        "values": [
            "interest in breadth/dual-honours study",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Keele (UK course-specific model) is distinctive for pioneering and championing DUAL HONOURS - many students combine two subjects - on a large, scenic parkland campus, with a well-regarded medical school and strengths in the sciences. Admission is grades + personal statement (Medicine requires the UCAT and interview), typically around ABB-BBB for most courses. If you're drawn to combining subjects, say so specifically. Make the personal statement subject-focused with genuine engagement.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement; interest in Keele's dual-honours breadth is a genuine fit signal, and subject depth recurs per UK admissions. Medicine is notably more competitive."
    },
    {
        "name": "Oxford Brookes University",
        "aka": [
            "oxford brookes",
            "brookes",
            "oxford brookes university"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~80-90% offer rate (course-dependent)",
        "region": "Oxford, England",
        "dataDepth": "deep",
        "motto": "One of the UK's leading post-92 universities, especially renowned for architecture, its ACCA-partnered accounting degree, occupational therapy, and publishing.",
        "values": [
            "strong subject ability",
            "a career/professional orientation",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Oxford Brookes (UK course-specific model) is consistently one of the top post-1992 universities, with genuine standout strengths in architecture, applied accounting (via a long-standing ACCA partnership), occupational therapy (it ran the UK's first such school), and publishing. Admission is grades + personal statement, typically around BBB-BBC (architecture and health routes more competitive, some with portfolio/interview). Make the personal statement subject-focused; its professional programmes reward genuine, specific interest.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement, often with a professional or career orientation fitting Brookes's applied strengths; for architecture and health programmes, demonstrated specific interest (or portfolio) recurs per UK admissions."
    },
    {
        "name": "Nottingham Trent University (NTU)",
        "aka": [
            "nottingham trent",
            "ntu",
            "nottingham trent university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~90% offer rate (course-dependent)",
        "region": "Nottingham, England",
        "dataDepth": "general",
        "motto": "A large, employability-focused post-92 university with strong industry links and recognised strengths in fashion, art and design, and business.",
        "values": [
            "a career/employability orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Nottingham Trent (UK course-specific model) is a large post-92 university built around employability and practical, industry-linked learning, with genuine strengths in fashion, art and design, business, and sports science. Admission is grades + personal statement, with a generous offer rate (~90%); creative courses may require a portfolio. Make the personal statement subject-focused and, for its career-oriented programmes, show genuine interest in real-world application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for creative courses a portfolio matters. Academic/course fit and genuine interest are the recurring signals per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Coventry University",
        "aka": [
            "coventry",
            "coventry university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~88% offer rate (course-dependent)",
        "region": "Coventry, England",
        "dataDepth": "general",
        "motto": "A large, strongly employability-focused post-92 university with industry-linked programmes in engineering, design, business, and health, and a strong reputation for student experience.",
        "values": [
            "a career/employability orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Coventry (UK course-specific model) is a post-92 university with a strong employability and industry-partnership focus, known for engineering, automotive/transport design, business, and health programmes, plus a good student-experience reputation. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application for its career-oriented courses. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/career orientation; course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Northumbria University",
        "aka": [
            "northumbria",
            "northumbria university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~90% offer rate (course-dependent)",
        "region": "Newcastle upon Tyne, England",
        "dataDepth": "general",
        "motto": "A large Newcastle post-92 university with strong reputations in design (its design school is highly regarded), law, business, and nursing, and a growing research profile.",
        "values": [
            "strong subject ability",
            "a career/professional orientation",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Northumbria (UK course-specific model) is a large Newcastle post-92 university with a genuinely strong design school (notable alumni including major product/industrial designers), plus well-regarded law, business, and nursing, and a rising research profile. Admission is grades + personal statement, with a generous offer rate; design routes require a portfolio. Make the personal statement subject-focused; creative and professional programmes reward genuine, specific interest. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for design a portfolio is central. Course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Bournemouth University",
        "aka": [
            "bournemouth",
            "bournemouth university",
            "bu bournemouth"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Bournemouth, England",
        "dataDepth": "general",
        "motto": "A post-92 university internationally renowned for media production, animation, and visual effects - its National Centre for Computer Animation has contributed to Oscar-winning films.",
        "values": [
            "a creative/media portfolio and passion",
            "strong subject ability",
            "genuine interest in the course",
            "a subject-focused personal statement"
        ],
        "guidance": "Bournemouth (UK course-specific model) is a post-92 university with a world-class reputation in media, animation, and visual effects - its National Centre for Computer Animation has graduates who've worked on Oscar-winning VFX. It's also strong in media production, journalism, and tourism. Admission is grades + personal statement, and its signature creative courses typically require a portfolio and show demonstrated passion. Make the personal statement subject-focused; for creative programmes, portfolio and genuine creative engagement are central. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): for its signature media/animation/VFX courses, admits present a strong portfolio and demonstrated creative passion; for other courses, grade requirements plus a subject-focused personal statement. Course fit and genuine interest recur per UK admissions."
    },
    {
        "name": "University of Portsmouth",
        "aka": [
            "portsmouth",
            "university of portsmouth"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Portsmouth, England",
        "dataDepth": "general",
        "motto": "One of the stronger-performing post-92 universities, with recognised strengths in forensic science, cosmology, criminology, and a strong graduate-employment and student-experience record.",
        "values": [
            "strong subject ability",
            "a career/professional orientation",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Portsmouth (UK course-specific model) is among the better-performing post-92 universities, known for forensic science, cosmology/astrophysics (a strong research group), criminology, and good graduate employability. Admission is grades + personal statement, with a generous offer rate for many courses. Make the personal statement subject-focused with genuine engagement; its signature programmes reward demonstrated specific interest. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement showing genuine interest; course fit and subject engagement recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Plymouth",
        "aka": [
            "plymouth",
            "university of plymouth"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Plymouth, England",
        "dataDepth": "general",
        "motto": "A post-92 university with genuine world-class strength in marine and ocean sciences (its coastal location and marine research are standout), plus medicine, health, and the sciences.",
        "values": [
            "strong subject ability",
            "genuine interest in the course (esp. marine/health)",
            "a subject-focused personal statement",
            "academic fit"
        ],
        "guidance": "Plymouth (UK course-specific model) is a post-92 university with genuinely world-leading marine and ocean science (its coastal setting and marine research are a real distinction), plus a medical school (Peninsula), health sciences, and psychology. Admission is grades + personal statement (Medicine/Dentistry require tests and interviews). Make the personal statement subject-focused; its marine and health programmes reward demonstrated, specific interest. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with demonstrated interest for its signature marine/health programmes; course fit recurs per UK admissions. Medicine is notably more competitive."
    },
    {
        "name": "University of Hull",
        "aka": [
            "hull",
            "university of hull"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Hull, England",
        "dataDepth": "general",
        "motto": "\"Lampada ferens\" — \"Carrying the torch of learning.\" A civic university (founded 1927) with strengths in medicine (Hull York Medical School), nursing, and a strong widening-participation mission.",
        "values": [
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course",
            "academic fit"
        ],
        "guidance": "Hull (UK course-specific model) is a civic university with a strong widening-participation ethos, a medical school (the Hull York Medical School, jointly with York), and strengths in nursing, health, and the humanities. Admission is grades + personal statement (Medicine requires the UCAT and interview), with a generous offer rate for many courses. Make the personal statement subject-focused with genuine engagement. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement showing genuine interest; course fit recurs per UK admissions, with Medicine more competitive. Verify exact requirements on the course page."
    },
    {
        "name": "De Montfort University (DMU)",
        "aka": [
            "de montfort",
            "dmu",
            "de montfort university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~89% offer rate (course-dependent)",
        "region": "Leicester, England",
        "dataDepth": "general",
        "motto": "A large Leicester post-92 university with strong reputations in art and design (fashion, contour fashion), law, and pharmacy, and a strong widening-participation and employability focus.",
        "values": [
            "a creative/professional orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "De Montfort (UK course-specific model) is a large Leicester post-92 university with genuine strengths in art and design (its fashion and contour-fashion programmes are notable), law, pharmacy, and a strong employability and widening-participation focus. Admission is grades + personal statement, with a generous offer rate; creative courses require a portfolio. Make the personal statement subject-focused; its creative and professional programmes reward genuine, specific interest. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for art and design a portfolio is central. Course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of the Arts London (UAL)",
        "aka": [
            "ual",
            "university of the arts london",
            "university of arts london",
            "central saint martins"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~60-70% offer rate (portfolio-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "The world's leading specialist art-and-design university (consistently ranked #2 globally for art & design), a federation of six colleges including Central Saint Martins, London College of Fashion, and Chelsea.",
        "values": [
            "an exceptional creative portfolio",
            "genuine artistic voice and process",
            "fit with the specific college/discipline",
            "creative risk-taking"
        ],
        "guidance": "UAL (UK creative-specialist model) is the world's foremost art-and-design university, made up of six renowned colleges (Central Saint Martins, London College of Fashion, Chelsea, Camberwell, Wimbledon, London College of Communication). Admission is portfolio-central - your creative work matters far more than grades, and many courses interview. Show a genuine artistic voice, strong process/sketchbook work (not just finished pieces), and fit with your specific college and discipline. Foundation diplomas are a common route in.",
        "acceptedPattern": "Admits stand out through an exceptional, distinctive portfolio that shows process and ideas (not just polished outcomes) and a genuine creative voice; interview performance and fit with the specific college/discipline recur. Grades matter far less than the portfolio at UAL."
    },
    {
        "name": "Goldsmiths, University of London",
        "aka": [
            "goldsmiths",
            "goldsmiths university of london",
            "goldsmiths university"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "A University of London college internationally known for creativity and unconventional, critical approaches - especially fine art (alumni include Damien Hirst, Steve McQueen), media, design, computing, and the social sciences.",
        "values": [
            "creative and critical originality",
            "a portfolio (for art/design)",
            "intellectual unconventionality",
            "genuine interest in the discipline"
        ],
        "guidance": "Goldsmiths (UK course-specific model) is famed for creativity, critical thinking, and an unconventional ethos - its fine art programme has produced Turner Prize winners and its media, computing, and social sciences are strongly research-led (80% of research rated world-leading/internationally excellent, REF 2021). Art and design routes are portfolio-based; academic courses are grades + personal statement. Show genuine creative or critical originality and fit with its distinctive, boundary-pushing approach.",
        "acceptedPattern": "For art/design, admits present a distinctive, conceptually strong portfolio; for academic courses, a subject-focused personal statement showing genuine critical or creative originality. The recurring signal is unconventional intellectual/creative voice and fit with Goldsmiths's ethos."
    },
    {
        "name": "Falmouth University",
        "aka": [
            "falmouth",
            "falmouth university"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (portfolio-dependent)",
        "region": "Falmouth, Cornwall, England",
        "dataDepth": "deep",
        "motto": "A specialist creative-arts university in Cornwall with strong reputations in photography, film, game arts, illustration, and creative writing, in a distinctive coastal setting.",
        "values": [
            "a strong creative portfolio",
            "genuine creative passion",
            "fit with the specific creative discipline",
            "originality"
        ],
        "guidance": "Falmouth (UK creative-specialist model) is a dedicated arts university in Cornwall with genuine strengths in photography, film & television, game arts/design, illustration, and creative writing. Admission is portfolio- and passion-driven for creative courses (with interviews for many), and grades matter less than demonstrated creative ability and potential. Show a distinctive portfolio, real creative process, and genuine fit with your specific discipline. Its coastal, creative-community setting is part of the draw.",
        "acceptedPattern": "Admits present a strong, distinctive portfolio and genuine creative passion for their specific discipline; interview/portfolio review is central and grades matter less. Creative voice and fit recur among those admitted."
    },
    {
        "name": "Manchester Metropolitan University (MMU)",
        "aka": [
            "manchester metropolitan",
            "mmu",
            "manchester met",
            "manchester metropolitan university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Manchester, England",
        "dataDepth": "general",
        "motto": "A large Manchester post-92 university with strong reputations in art and design (the Manchester School of Art), fashion, and a broad range of professional and applied programmes.",
        "values": [
            "strong subject ability",
            "a portfolio (for creative courses)",
            "a career/professional orientation",
            "genuine interest in the course"
        ],
        "guidance": "Manchester Metropolitan (UK course-specific model) is a large post-92 university with a well-regarded Manchester School of Art, plus strong fashion, business, and applied/professional programmes, in a vibrant city. Admission is grades + personal statement (creative courses require a portfolio), with a generous offer rate. Make the personal statement subject-focused; creative programmes reward a strong portfolio. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for art/design a portfolio is central. Course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Sheffield Hallam University",
        "aka": [
            "sheffield hallam",
            "hallam",
            "sheffield hallam university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Sheffield, England",
        "dataDepth": "general",
        "motto": "A large Sheffield post-92 university with a strong applied, employability-focused ethos and recognised programmes in sport, health, engineering, and the built environment.",
        "values": [
            "a career/employability orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Sheffield Hallam (UK course-specific model) is one of the UK's largest post-92 universities, with a strong applied/employability focus and well-regarded programmes in sport, health, nursing, engineering, and the built environment. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and, for its career-oriented courses, show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/career orientation; course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of the West of England (UWE Bristol)",
        "aka": [
            "uwe",
            "uwe bristol",
            "university of the west of england",
            "west of england"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Bristol, England",
        "dataDepth": "general",
        "motto": "A large Bristol post-92 university with a strong applied, professional focus and recognised programmes in engineering (with aerospace links), health, business, and art & design.",
        "values": [
            "a career/professional orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "UWE Bristol (UK course-specific model) is a large post-92 university with a strong professional/applied ethos and industry links (notably aerospace and engineering in the Bristol area), plus health, business, and art & design. Admission is grades + personal statement (creative courses require a portfolio), with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/career orientation; for art/design a portfolio matters. Course fit recurs per UK admissions."
    },
    {
        "name": "Leeds Beckett University",
        "aka": [
            "leeds beckett",
            "leeds beckett university",
            "leeds met"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Leeds, England",
        "dataDepth": "general",
        "motto": "A large Leeds post-92 university with an applied, employability-focused ethos and recognised programmes in sport, the built environment, and business.",
        "values": [
            "a career/employability orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Leeds Beckett (UK course-specific model) is a large post-92 university with a practical, employability focus and well-regarded programmes in sport (a genuine strength), the built environment/architecture, and business. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application for its career-oriented courses. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/career orientation; course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Robert Gordon University (RGU)",
        "aka": [
            "robert gordon",
            "rgu",
            "robert gordon university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~80-90% offer rate (course-dependent)",
        "region": "Aberdeen, Scotland",
        "dataDepth": "general",
        "motto": "An Aberdeen post-92 university with a strong graduate-employability record and applied programmes in energy/engineering, health, pharmacy, and business, with strong industry links.",
        "values": [
            "a career/professional orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Robert Gordon (UK course-specific model) is an Aberdeen university with a consistently strong graduate-employment record and applied, industry-linked programmes in energy/engineering (North Sea links), health, pharmacy, and business. Admission is grades + personal statement (Scottish structure). Make the personal statement subject-focused and show genuine interest in practical/professional application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's requirements and present a subject-focused personal statement, often with a practical/professional orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Glasgow Caledonian University (GCU)",
        "aka": [
            "glasgow caledonian",
            "gcu",
            "glasgow caledonian university",
            "caledonian"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~80-90% offer rate (course-dependent)",
        "region": "Glasgow, Scotland",
        "dataDepth": "general",
        "motto": "\"For the Common Good.\" A Glasgow post-92 university with a strong social-mission ethos and applied programmes in health/nursing, engineering, and business.",
        "values": [
            "a social-good and community orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Glasgow Caledonian (UK course-specific model) is a Glasgow university with a genuine 'University for the Common Good' social mission, strong in health and nursing, engineering, the built environment, and business. Admission is grades + personal statement (Scottish structure). Make the personal statement subject-focused; a genuine social-good or community orientation fits its ethos well. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's requirements and present a subject-focused personal statement, often with a practical or social-good orientation fitting its mission; course fit recurs per UK admissions."
    },
    {
        "name": "Abertay University",
        "aka": [
            "abertay",
            "abertay university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~80-90% offer rate (course-dependent)",
        "region": "Dundee, Scotland",
        "dataDepth": "general",
        "motto": "A small Dundee post-92 university that pioneered UK computer-games education - it offered the world's first computer-games degrees and remains a leading name in games and cyber-security.",
        "values": [
            "genuine passion for games/computing",
            "a portfolio or demonstrated projects",
            "strong subject ability",
            "a subject-focused personal statement"
        ],
        "guidance": "Abertay (UK course-specific model) is a small Dundee university with a genuinely distinctive claim: it launched the world's first computer-games technology and design degrees and is a leading UK name in games development and cyber-security. Admission is grades + personal statement (Scottish structure); games/creative routes value demonstrated projects or a portfolio. Make the personal statement subject-focused; for games and computing, real projects and genuine passion read especially well. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): for its signature games/computing programmes, admits show genuine passion and demonstrated projects; otherwise, grade requirements plus a subject-focused personal statement. Course fit and genuine interest recur per UK admissions."
    },
    {
        "name": "Royal Academy of Dramatic Art (RADA)",
        "aka": [
            "rada",
            "royal academy of dramatic art"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "extremely competitive (audition-based; a tiny cohort)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "The world's most renowned drama school (founded 1904) - alumni include generations of leading actors - with an intensely selective, audition-based admissions process.",
        "values": [
            "exceptional performance talent and potential",
            "authenticity and presence at audition",
            "commitment to the craft",
            "coachability"
        ],
        "guidance": "RADA (UK conservatoire/drama-school model) is the most famous drama school in the world, training a very small cohort each year through a rigorous, multi-round audition process (largely its own private process, separate from standard UCAS). Grades are essentially irrelevant - everything rests on audition performance, presence, and potential. Prepare contrasting monologues to the exact brief, show authenticity and range rather than performed 'polish,' and demonstrate genuine commitment to acting as a craft. Expect multiple recall rounds and workshops.",
        "acceptedPattern": "Admits stand out purely through audition - raw talent, authenticity, presence, emotional availability, and coachability across recall rounds and workshops. Academic record is not the point; the recurring signal is genuine performing potential and commitment to the craft."
    },
    {
        "name": "Guildhall School of Music and Drama",
        "aka": [
            "guildhall",
            "guildhall school",
            "guildhall school of music and drama",
            "gsmd"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "extremely competitive (audition-based)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "A world-leading conservatoire (ranked #1 in the UK and #3 globally for music) at the Barbican, training musicians, actors, and production artists - including a rare, strong jazz programme.",
        "values": [
            "exceptional musical/dramatic talent",
            "audition performance",
            "artistic potential and musicianship",
            "commitment to the craft"
        ],
        "guidance": "Guildhall (UK conservatoire model) is among the world's top conservatoires, training classical and jazz musicians, actors, and production artists at the Barbican (home of the LSO). Music applicants apply via UCAS Conservatoires and are admitted primarily on AUDITION (in-person or video); drama runs its own audition process. Grades matter far less than performance. Prepare your audition repertoire meticulously to the specified requirements, and show genuine musicianship/dramatic potential and commitment. Its jazz programme is a rare UK strength.",
        "acceptedPattern": "Admits are selected principally on audition - technical excellence, musicianship or dramatic potential, and artistic promise - with grades a minor factor. The recurring signal is performance quality and genuine artistic potential at audition/recall."
    },
    {
        "name": "Royal College of Music (RCM)",
        "aka": [
            "rcm",
            "royal college of music"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "extremely competitive (audition-based)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "A world-leading music conservatoire (consistently top-ranked globally) training performers and composers to the highest level.",
        "values": [
            "exceptional performance ability",
            "audition/portfolio quality",
            "musicianship and artistic potential",
            "commitment to the craft"
        ],
        "guidance": "RCM (UK conservatoire model) is one of the world's top music conservatoires. Its own guidance is explicit: 'the main basis for admission is your performance at audition' (in person or video); composers are admitted on the strength of their portfolio and interview. Apply via UCAS Conservatoires, then submit audition materials. Grades are a minor factor. Prepare your audition repertoire (or composition portfolio) to the exact requirements, and demonstrate genuine musicianship and artistic potential.",
        "acceptedPattern": "Admits are chosen on audition (performers) or portfolio + interview (composers) - technical mastery, musicianship, and artistic potential are decisive, and grades matter little. Performance/portfolio quality is the recurring signal, per RCM's own stated basis for admission."
    },
    {
        "name": "Norwich University of the Arts (NUA)",
        "aka": [
            "norwich university of the arts",
            "nua",
            "norwich arts"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (portfolio-dependent)",
        "region": "Norwich, England",
        "dataDepth": "deep",
        "motto": "A specialist arts university with strong reputations in illustration, animation, graphic design, film, and fashion, known for a focused creative-community ethos.",
        "values": [
            "a strong creative portfolio",
            "genuine creative voice",
            "fit with the specific discipline",
            "originality"
        ],
        "guidance": "Norwich University of the Arts (UK creative-specialist model) is a dedicated arts university with genuine strengths in illustration, animation, graphic communication design, film, and fashion. Admission is portfolio- and interview-based for creative courses, and grades matter less than demonstrated creative ability and potential. Show a distinctive portfolio (with process, not just outcomes), a genuine creative voice, and fit with your specific discipline.",
        "acceptedPattern": "Admits present a strong, distinctive portfolio and genuine creative voice for their specific discipline; portfolio/interview is central and grades matter less. Creative potential and fit recur among those admitted."
    },
    {
        "name": "Arts University Bournemouth (AUB)",
        "aka": [
            "arts university bournemouth",
            "aub",
            "aub bournemouth"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "~70-80% offer rate (portfolio-dependent)",
        "region": "Bournemouth, England",
        "dataDepth": "deep",
        "motto": "A specialist arts university with strong reputations in animation, film, visual effects, architecture, and design - a focused creative institution distinct from the nearby Bournemouth University.",
        "values": [
            "a strong creative portfolio",
            "genuine creative passion",
            "fit with the specific discipline",
            "originality"
        ],
        "guidance": "Arts University Bournemouth (UK creative-specialist model) is a dedicated arts university (distinct from Bournemouth University) with genuine strengths in animation, film, visual effects, architecture, and a broad range of art and design. Admission is portfolio- and interview-based for creative courses, with grades a secondary factor. Show a distinctive portfolio demonstrating process and ideas, genuine creative passion, and fit with your specific discipline.",
        "acceptedPattern": "Admits present a strong, distinctive portfolio and genuine creative passion for their specific discipline; portfolio/interview is central and grades matter less. Creative potential and fit recur among those admitted."
    },
    {
        "name": "Kingston University",
        "aka": [
            "kingston",
            "kingston university",
            "kingston university london"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "general",
        "motto": "A large London post-92 university with strong reputations in art, design, and fashion (its fashion programme is highly regarded), plus a broad range of professional courses.",
        "values": [
            "a portfolio (for creative courses)",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Kingston (UK course-specific model) is a large London post-92 university with a genuinely strong art, design, and fashion school (its fashion course has a notable industry reputation), plus broad professional programmes. Admission is grades + personal statement (creative courses require a portfolio and often interview), with a generous offer rate. Make the personal statement subject-focused; creative programmes reward a strong portfolio. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for art/design/fashion a portfolio is central. Course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Middlesex University",
        "aka": [
            "middlesex",
            "middlesex university",
            "mdx"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "general",
        "motto": "A large, diverse London post-92 university with applied programmes across business, health, art & design, and a strong widening-participation and international focus.",
        "values": [
            "a career/professional orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Middlesex (UK course-specific model) is a large, diverse London post-92 university with a strong widening-participation and international student focus, and applied programmes in business, health, nursing, and art & design. Admission is grades + personal statement (creative courses require a portfolio), with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for creative courses a portfolio matters. Course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Brighton",
        "aka": [
            "brighton",
            "university of brighton"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Brighton, England",
        "dataDepth": "general",
        "motto": "A post-92 university with strong reputations in art and design (a genuine creative strength), architecture, and health, in the vibrant seaside city of Brighton.",
        "values": [
            "a portfolio (for creative courses)",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Brighton (UK course-specific model) is a post-92 university with a genuinely well-regarded art and design school, plus architecture, health, and education, in a lively coastal city. Admission is grades + personal statement (creative courses require a portfolio and often interview), with a generous offer rate. Make the personal statement subject-focused; creative programmes reward a strong portfolio. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for art/design a portfolio is central. Course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Liverpool John Moores University (LJMU)",
        "aka": [
            "liverpool john moores",
            "ljmu",
            "john moores"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Liverpool, England",
        "dataDepth": "general",
        "motto": "A large Liverpool post-92 university with an applied, employability-focused ethos and recognised programmes in astrophysics, sport science, forensic science, and the built environment.",
        "values": [
            "a career/applied orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Liverpool John Moores (UK course-specific model) is a large post-92 university with a strong applied and employability focus, and some genuinely notable strengths - it runs one of the world's largest robotic telescopes (astrophysics), plus sport science, forensic science, and the built environment. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/applied orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Teesside University",
        "aka": [
            "teesside",
            "teesside university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Middlesbrough, England",
        "dataDepth": "general",
        "motto": "A post-92 university internationally recognised for computer games and animation (its games/VFX programmes and the Animex festival are notable), plus strong health and engineering.",
        "values": [
            "a portfolio/projects (for games/creative)",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Teesside (UK course-specific model) is a post-92 university in the northeast with a genuine international reputation for computer games and animation (it hosts the Animex international festival and its graduates work across the games/VFX industry), plus health and engineering. Admission is grades + personal statement (games/creative routes value demonstrated projects or a portfolio), with a generous offer rate. Make the personal statement subject-focused; for games and creative programmes, real projects and genuine passion read well. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): for its signature games/animation programmes, admits show genuine passion and demonstrated projects; otherwise, grade requirements plus a subject-focused personal statement. Course fit and genuine interest recur per UK admissions."
    },
    {
        "name": "Aberystwyth University",
        "aka": [
            "aberystwyth",
            "aberystwyth university",
            "aber"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Aberystwyth, Wales",
        "dataDepth": "deep",
        "motto": "\"Nid Byd, Byd Heb Wybodaeth\" — \"A world without knowledge is no world at all.\" A historic Welsh university (founded 1872) - notably the birthplace of the academic discipline of International Politics.",
        "values": [
            "genuine subject interest (esp. international politics/history)",
            "strong subject ability",
            "a subject-focused personal statement",
            "academic fit"
        ],
        "guidance": "Aberystwyth (UK course-specific model) is a historic seaside Welsh university with a genuine claim to fame: the world's first department of International Politics was founded here in 1919, and it remains a strength alongside history, geography, and the environmental sciences. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused; its signature international-politics and history programmes reward demonstrated, specific interest.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement with genuine engagement, often with demonstrated interest for its signature international-politics or history programmes; subject fit recurs per UK admissions."
    },
    {
        "name": "Bangor University",
        "aka": [
            "bangor",
            "bangor university",
            "prifysgol bangor"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Bangor, Wales",
        "dataDepth": "general",
        "motto": "A historic Welsh university (founded 1884) between Snowdonia and the sea, with genuine strengths in ocean sciences, environmental science, psychology, and history.",
        "values": [
            "strong subject ability",
            "genuine interest in the course",
            "a subject-focused personal statement",
            "academic fit"
        ],
        "guidance": "Bangor (UK course-specific model) is a historic Welsh university in a striking natural setting, with real strengths in ocean/marine sciences, environmental science, psychology, and history. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused with genuine engagement; its signature science programmes reward demonstrated interest. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement showing genuine interest; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Ulster University",
        "aka": [
            "ulster",
            "ulster university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Belfast, Northern Ireland",
        "dataDepth": "general",
        "motto": "A large multi-campus Northern Irish university (Belfast, Coleraine, Derry/Magee, plus branch campuses) with strengths in art & design, health, and biomedical sciences.",
        "values": [
            "strong subject ability",
            "a career/professional orientation",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Ulster (UK course-specific model) is a large Northern Irish university spread across several campuses, with genuine strengths in art & design (the Belfast School of Art), health and nursing, and biomedical sciences. Admission is grades + personal statement (creative courses require a portfolio; some health courses require interviews), with a generous offer rate. Make the personal statement subject-focused. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for art/design a portfolio matters. Course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Lincoln",
        "aka": [
            "lincoln",
            "university of lincoln"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Lincoln, England",
        "dataDepth": "general",
        "motto": "A modern university (its city-centre campus opened in 1996) that has risen quickly, known for strong student satisfaction and industry-linked programmes in engineering, agri-food, and the sciences.",
        "values": [
            "strong subject ability",
            "a career/professional orientation",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Lincoln (UK course-specific model) is a fast-rising modern university with a strong student-satisfaction record and genuine industry links - its engineering school was founded in partnership with Siemens, and it has notable agri-food and science programmes. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application for its industry-linked courses. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/career orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Salford",
        "aka": [
            "salford",
            "university of salford"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Salford, Greater Manchester, England",
        "dataDepth": "general",
        "motto": "A Greater Manchester post-92 university with a strong media focus - it has a major campus at MediaCityUK (home to parts of the BBC and ITV) - plus health, engineering, and the built environment.",
        "values": [
            "a media/career orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Salford (UK course-specific model) is a Greater Manchester post-92 university with a genuine media distinction - it has a campus at MediaCityUK alongside the BBC and ITV, giving strong industry links for media, journalism, and production - plus health, engineering, and the built environment. Admission is grades + personal statement (creative/media courses may need a portfolio), with a generous offer rate. Make the personal statement subject-focused; media programmes reward genuine, specific interest. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a media/practical orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Huddersfield",
        "aka": [
            "huddersfield",
            "university of huddersfield"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Huddersfield, England",
        "dataDepth": "general",
        "motto": "A post-92 university with a strong teaching-quality reputation and applied programmes in music/music technology, engineering, and health, plus a strong focus on professional accreditation.",
        "values": [
            "a career/professional orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Huddersfield (UK course-specific model) is a post-92 university known for strong teaching quality and applied, professionally-accredited programmes, with genuine strengths in music and music technology, engineering, and health. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/professional orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Bradford",
        "aka": [
            "bradford",
            "university of bradford"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Bradford, England",
        "dataDepth": "general",
        "motto": "\"Give invention light.\" A post-92 university with a strong social-mobility record and applied programmes in health, pharmacy, engineering, and management.",
        "values": [
            "a career/professional orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Bradford (UK course-specific model) is a post-92 university with a genuinely strong social-mobility record and applied, professionally-focused programmes in health, pharmacy, engineering, and management. Admission is grades + personal statement (health/pharmacy routes may need interviews), with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/professional orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Bath Spa University",
        "aka": [
            "bath spa",
            "bath spa university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (portfolio-dependent)",
        "region": "Bath, England",
        "dataDepth": "general",
        "motto": "A post-92 university with a strong creative-arts focus - art and design, creative writing, and education - on scenic campuses near the historic city of Bath.",
        "values": [
            "a portfolio/creative passion",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Bath Spa (UK course-specific model) is a post-92 university with a genuine creative-arts identity - art and design, creative writing, music, and education - on attractive campuses near Bath. Admission is grades + personal statement (creative courses require a portfolio or audition), with a generous offer rate. Make the personal statement subject-focused; creative programmes reward a strong portfolio and genuine creative passion. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for creative courses a portfolio matters. Course fit and genuine interest recur per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Chester",
        "aka": [
            "chester",
            "university of chester"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Chester, England",
        "dataDepth": "general",
        "motto": "One of England's longest-established higher-education institutions (its origins date to 1839), a university with a strong focus on health, education, and the professions.",
        "values": [
            "a career/professional orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Chester (UK course-specific model) is a university with a long teaching heritage (among the oldest English HE institutions, dating to 1839) and applied strengths in health, nursing, education, and the professions, across several campuses. Admission is grades + personal statement (health/education routes may need interviews and checks), with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/professional orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Edinburgh Napier University",
        "aka": [
            "edinburgh napier",
            "napier",
            "edinburgh napier university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Edinburgh, Scotland",
        "dataDepth": "general",
        "motto": "\"Nisi sapientia frustra\" — \"Without wisdom, all is in vain.\" An Edinburgh post-92 university with applied strengths in computing, engineering, nursing, and business, and strong industry links.",
        "values": [
            "a career/professional orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Edinburgh Napier (UK course-specific model) is an Edinburgh post-92 university with a practical, employability focus and genuine strengths in computing, engineering, nursing, and business. Admission is grades + personal statement (Scottish structure), with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical/professional application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's requirements and present a subject-focused personal statement, often with a practical/professional orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Westminster",
        "aka": [
            "westminster",
            "university of westminster"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "A central-London university (the UK's first polytechnic, 1838) with genuine strengths in media and communications, architecture, and fashion, and strong industry links in the capital.",
        "values": [
            "a portfolio/creative or media orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Westminster (UK course-specific model) was Britain's first polytechnic and has a genuine reputation in media and communications (film, journalism, broadcasting), architecture, and fashion, with strong London industry connections. Admission is grades + personal statement (creative/media and architecture courses require a portfolio and often interview), with a generous offer rate. Make the personal statement subject-focused; its signature creative and media programmes reward a strong portfolio and demonstrated interest.",
        "acceptedPattern": "Admits show the required grades and a subject-focused personal statement; for its signature media, architecture, and fashion programmes a strong portfolio and genuine, specific interest are central. Course fit recurs per UK admissions."
    },
    {
        "name": "Harper Adams University",
        "aka": [
            "harper adams",
            "harper adams university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Edgmond, Shropshire, England",
        "dataDepth": "deep",
        "motto": "\"Utile Dulci\" — \"Useful and agreeable.\" The UK's leading specialist land-based university - agriculture, food production, agri-engineering, animal sciences, and rural business.",
        "values": [
            "genuine interest in agriculture/land-based fields",
            "practical/hands-on experience",
            "a subject-focused personal statement",
            "fit with a specialist rural community"
        ],
        "guidance": "Harper Adams (UK specialist model) is the UK's foremost land-based university, dedicated to agriculture, food, agricultural engineering, animal sciences, veterinary nursing, and rural business, with outstanding graduate employability and a working farm. Admission is grades + personal statement, and it genuinely values relevant practical/farm/industry experience and a real commitment to the land-based sector. Make the personal statement specifically about your interest in agriculture/food/rural fields - demonstrated hands-on experience reads especially well here.",
        "acceptedPattern": "Admits show genuine, specific interest in land-based fields plus (very often) real practical or farm/industry experience, and fit with a specialist rural community; demonstrated commitment to agriculture/food and relevant experience recur, alongside meeting grade requirements."
    },
    {
        "name": "University of Hertfordshire",
        "aka": [
            "hertfordshire",
            "university of hertfordshire",
            "herts"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Hatfield, England",
        "dataDepth": "general",
        "motto": "A post-92 university near London with applied strengths in aerospace/automotive engineering, computer science, and business, plus strong industry links (it grew from de Havilland's aeronautical roots).",
        "values": [
            "a career/applied orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Hertfordshire (UK course-specific model) is a post-92 university near London with a practical, industry-linked focus and genuine strengths in aerospace and automotive engineering (its roots trace to the de Havilland aircraft company), computer science, and business. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical/applied study. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/applied orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Greenwich",
        "aka": [
            "greenwich",
            "university of greenwich"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "general",
        "motto": "A London post-92 university on a UNESCO World Heritage riverside campus, with applied strengths in engineering, pharmacy, business, and computing.",
        "values": [
            "a career/applied orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Greenwich (UK course-specific model) is a London post-92 university (its main campus occupies the historic Old Royal Naval College, a UNESCO World Heritage Site) with applied strengths in engineering, pharmacy, business, and computing. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/career orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Roehampton",
        "aka": [
            "roehampton",
            "university of roehampton"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "general",
        "motto": "A London collegiate university (Cathedrals Group) on a green campus, with recognised strengths in dance, education/teacher training, psychology, and the humanities.",
        "values": [
            "strong subject ability",
            "genuine interest in the course",
            "a subject-focused personal statement",
            "academic fit"
        ],
        "guidance": "Roehampton (UK course-specific model) is a London university with a collegiate structure and green campus, known for dance (a genuine strength), teacher training and education, psychology, and the humanities. Admission is grades + personal statement (dance/creative routes require audition/portfolio; teaching routes require interviews and checks), with a generous offer rate. Make the personal statement subject-focused with genuine engagement. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement; for dance/creative an audition or portfolio matters. Course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Staffordshire University",
        "aka": [
            "staffordshire",
            "staffordshire university",
            "staffs"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Stoke-on-Trent, England",
        "dataDepth": "general",
        "motto": "A post-92 university with a strong reputation in computer games design and esports (a genuine specialism), plus health, engineering, and forensic science.",
        "values": [
            "a portfolio/projects (for games/creative)",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Staffordshire (UK course-specific model) is a post-92 university with a genuine, long-standing specialism in computer games design and esports (it runs a dedicated Games Institute and esports facilities), plus health, engineering, and forensic science. Admission is grades + personal statement (games/creative routes value demonstrated projects or a portfolio), with a generous offer rate. Make the personal statement subject-focused; for games and creative programmes, real projects and genuine passion read well. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): for its signature games/esports programmes, admits show genuine passion and demonstrated projects; otherwise, grade requirements plus a subject-focused personal statement. Course fit recurs per UK admissions."
    },
    {
        "name": "University of Winchester",
        "aka": [
            "winchester",
            "university of winchester"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Winchester, England",
        "dataDepth": "general",
        "motto": "\"Wisdom and understanding.\" A small university (Cathedrals Group heritage) with a values-driven, social-justice ethos and strengths in education, the humanities, and social sciences.",
        "values": [
            "character and values fit",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Winchester (UK course-specific model) is a small university with a distinctive values-led, social-justice ethos, strong in education/teacher training, the humanities, and social sciences. Admission is grades + personal statement (education routes require interviews and checks), with a generous offer rate. Make the personal statement subject-focused; a genuine values or social-justice orientation fits its ethos. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, sometimes with a values/social-justice orientation fitting its ethos; course fit recurs per UK admissions."
    },
    {
        "name": "University of Derby",
        "aka": [
            "derby",
            "university of derby"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Derby, England",
        "dataDepth": "general",
        "motto": "A post-92 university with an applied, employability focus and recognised programmes in nursing/health, engineering, and one of the UK's leading spa/hospitality programmes at its Buxton campus.",
        "values": [
            "a career/applied orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Derby (UK course-specific model) is a post-92 university with a practical, employability focus and applied strengths in nursing/health, engineering, and hospitality/spa management (at its historic Buxton campus). Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/career orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "University of Northampton",
        "aka": [
            "northampton",
            "university of northampton"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Northampton, England",
        "dataDepth": "general",
        "motto": "A post-92 university with a strong social-enterprise and 'changemaker' ethos, on a modern waterside campus, with applied programmes in business, health, and education.",
        "values": [
            "a social-enterprise/changemaker orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Northampton (UK course-specific model) is a post-92 university on a modern campus with a distinctive social-enterprise and 'changemaker' identity, and applied programmes in business, health, and education. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused; a genuine social-enterprise or community orientation fits its ethos. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, sometimes with a social-enterprise orientation fitting its ethos; course fit recurs per UK admissions."
    },
    {
        "name": "University of Gloucestershire",
        "aka": [
            "gloucestershire",
            "university of gloucestershire"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Cheltenham, England",
        "dataDepth": "general",
        "motto": "A post-92 university across Cheltenham and Gloucester with applied strengths in sport, business, education, and the creative industries.",
        "values": [
            "a career/applied orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Gloucestershire (UK course-specific model) is a post-92 university with campuses across Cheltenham and Gloucester and applied strengths in sport, business, education, and the creative industries. Admission is grades + personal statement (creative courses may need a portfolio), with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/career orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "London South Bank University (LSBU)",
        "aka": [
            "london south bank",
            "lsbu",
            "south bank university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "general",
        "motto": "A London post-92 university with a strongly vocational, career-focused ethos and applied strengths in the built environment, engineering, health, and nursing.",
        "values": [
            "a career/vocational orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "London South Bank (UK course-specific model) is a London post-92 university with a genuinely vocational, employability-driven identity and applied strengths in the built environment, engineering, health, and nursing, with strong professional accreditation. Admission is grades + personal statement (health routes require interviews and checks), with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical/professional application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a strong practical/vocational orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    },
    {
        "name": "Solent University",
        "aka": [
            "solent",
            "solent university",
            "southampton solent"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Southampton, England",
        "dataDepth": "general",
        "motto": "A post-92 university in Southampton with distinctive strengths in maritime studies (a genuine specialism), media production, and sport.",
        "values": [
            "a career/applied orientation",
            "a portfolio (for media/creative)",
            "strong subject ability",
            "genuine interest in the course"
        ],
        "guidance": "Solent (UK course-specific model) is a Southampton post-92 university with a genuine maritime-studies specialism (Warsash Maritime School), plus media production, music, and sport. Admission is grades + personal statement (media/creative routes value a portfolio; maritime routes have specific requirements), with a generous offer rate. Make the personal statement subject-focused; its signature maritime and media programmes reward demonstrated, specific interest. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): for its signature maritime/media programmes, admits show genuine, specific interest (and a portfolio for media); otherwise, grade requirements plus a subject-focused personal statement. Course fit recurs per UK admissions."
    },
    {
        "name": "Anglia Ruskin University (ARU)",
        "aka": [
            "anglia ruskin",
            "aru",
            "anglia ruskin university"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "Cambridge & Chelmsford, England",
        "dataDepth": "general",
        "motto": "A large post-92 university (Cambridge and Chelmsford campuses) with a strong health and medical-education focus, a medical school, plus business and the arts.",
        "values": [
            "a career/professional orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "Anglia Ruskin (UK course-specific model) is a large post-92 university with campuses in Cambridge and Chelmsford, a strong focus on health and medical education (it has a medical school), plus nursing, business, and the arts. Admission is grades + personal statement (Medicine/health routes require tests, interviews, and checks), with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical/professional application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course's grade requirements and present a subject-focused personal statement, often with a practical/professional orientation; course fit recurs per UK admissions, with Medicine notably more competitive."
    },
    {
        "name": "University of East London (UEL)",
        "aka": [
            "uel",
            "university of east london",
            "east london"
        ],
        "country": "UK",
        "tier": "general",
        "accept": "~85-90% offer rate (course-dependent)",
        "region": "London, England",
        "dataDepth": "general",
        "motto": "A diverse East London post-92 university with a strong social-mobility mission and applied programmes in health, sport, business, and the creative industries.",
        "values": [
            "a career/applied orientation",
            "strong subject ability",
            "a subject-focused personal statement",
            "genuine interest in the course"
        ],
        "guidance": "University of East London (UK course-specific model) is a diverse East London post-92 university with a strong widening-participation and social-mobility mission, and applied programmes in health, sport (its SportsDock facilities are notable), business, and the creative industries. Admission is grades + personal statement, with a generous offer rate. Make the personal statement subject-focused and show genuine interest in practical application. (Source-verified for facts and entry model; detailed admitted-student pattern data is limited, so guidance here is general.)",
        "acceptedPattern": "General pattern (limited published admit-specific data): admits meet the course grade requirements and present a subject-focused personal statement, often with a practical/career orientation; course fit recurs per UK admissions. Verify exact requirements on the course page."
    }
]


def _norm(s: str) -> str:
    return str(s or "").strip().lower()


def _alias_matches(query_norm: str, alias: str) -> bool:
    """True if the alias genuinely matches the query. The query containing
    the alias only counts at a word boundary, so short aliases like 'cal'
    or 'nd' don't spuriously match inside unrelated words (e.g. 'cal' in
    'some local college'). The alias containing the query is fine (typing
    a prefix like 'harv')."""
    import re as _re
    if query_norm in alias:
        return True
    return bool(_re.search(r"\b" + _re.escape(alias) + r"\b", query_norm))


def search_schools(query: str) -> list[dict]:
    """Search the KB by name or alias - powers the survey autocomplete.
    Mirrors the frontend searchSchools() exactly."""
    q = _norm(query)
    if not q:
        return []
    out = []
    for s in SCHOOLS:
        name = s["name"].lower()
        aka = s.get("aka", [])
        if q in name or any(_alias_matches(q, a) for a in aka):
            out.append(s)
        if len(out) >= 6:
            break
    return out


def lookup_school(name: str):
    """Resolve a stored school name (or free text) to its KB entry, or None.
    Mirrors the frontend lookupSchool() exactly."""
    q = _norm(name)
    if not q:
        return None
    # exact / alias first, then substring, matching the frontend precedence
    for s in SCHOOLS:
        if s["name"].lower() == q or q in s.get("aka", []):
            return s
    # Substring / alias-fuzzy pass, but ONLY for a query specific enough to be
    # meaningful. A too-short or generic query ("a", "the", "college", "state")
    # would otherwise fuzzy-match a specific, often highly-selective school
    # (Harvard, Dartmouth) - via either the name substring OR the loose
    # alias-match - and silently anchor a student's whole roadmap/readiness on
    # the WRONG school. Generic queries resolve to None ("general guidance").
    _GENERIC = {"a", "the", "of", "in", "at", "college", "university", "state",
                "institute", "school", "and", "for", "new", "san", "los", "the university"}
    if len(q) >= 4 and q not in _GENERIC:
        for s in SCHOOLS:
            if q in s["name"].lower() or any(_alias_matches(q, a) for a in s.get("aka", [])):
                return s
    return None


def target_school_entries(target_schools: str) -> list[dict]:
    """Resolve a student's comma-separated target_schools string to the
    KB entries that are found. Unknown schools are simply omitted (the
    caller reports them honestly as 'general guidance')."""
    names = [n.strip() for n in (target_schools or "").split(",") if n.strip()]
    entries = []
    for n in names:
        e = lookup_school(n)
        if e and e not in entries:
            entries.append(e)
    return entries


def _anchor_school(entries: list[dict]):
    """The school that sets the bar - the most selective (reach) one,
    else the first. Advice anchors on this. Mirrors the frontend."""
    if not entries:
        return None
    for e in entries:
        if e.get("tier") == "reach":
            return e
    return entries[0]


def tailor_advice_for_opportunity(opp: dict, profile: dict) -> str:
    """The school-specific "why this fits" for one opportunity, tailored to
    the student's target schools. Honest and deterministic - never a
    fabricated per-officer claim. Mirrors the frontend deepExplain()."""
    major = profile.get("intended_major") or "your intended field"
    tags = opp.get("tags", []) or []
    matched = (opp.get("matched") or [])[:3]
    overlap = ", ".join(matched)

    if "competition" in tags:
        kind = "A strong result here is a concrete, verifiable achievement"
    elif "internship" in tags:
        kind = "Real hands-on experience like this shows genuine, tested interest"
    elif "leadership" in tags:
        kind = "Sustained leadership here demonstrates initiative over time"
    else:
        kind = "Consistent involvement here shows real, demonstrated commitment"

    overlap_line = (
        f"This overlaps directly with your stated focus on {overlap}. "
        if overlap else
        f"This is a broader activity - useful while you narrow your focus, but pair it with something more specific to {major}. "
    )

    entries = target_school_entries(profile.get("target_schools", ""))
    school_line = " Depth in one or two areas reads far stronger than a long list of shallow activities."
    anchor = _anchor_school(entries)
    if anchor:
        vals = anchor.get("values", [])
        value_match = None
        for v in vals:
            vl = v.lower()
            first = vl.split(" ")[0] if vl else ""
            if any(vl in t or (first and first in t) for t in tags) \
               or (("leadership" in vl) and ("leadership" in tags)) \
               or (("making" in vl) and ("competition" in tags)) \
               or (("building" in vl) and ("entrepreneurship" in tags)):
                value_match = v
                break
        two_values = " and ".join(vals[:2]) if vals else "genuine depth"
        if value_match:
            school_line = (
                f" For {anchor['name']} ({anchor['accept']} admit rate), what actually moves the "
                f"needle is {two_values} - and this opportunity speaks directly to that."
            )
        else:
            school_line = (
                f" For {anchor['name']} ({anchor['accept']} admit rate), what actually moves the "
                f"needle is {two_values}, so make sure this connects to a genuine, deep interest "
                f"rather than sitting on a list."
            )

    return (
        f"{overlap_line}{kind} in {major}.{school_line} "
        "Add it to your tracker to get it onto your schedule with its real deadline."
    )


def school_guidance_for_profile(profile: dict) -> dict:
    """The full school-tailored guidance payload for a student's dashboard:
    each matched target school's real profile + guidance, plus an honest
    note for any target schools not in the curated KB.

    Returns:
        {
          "schools": [ {name, country, tier, accept, region, motto,
                        values, guidance, acceptedPattern}, ... ],
          "uncurated": ["Some Local College", ...],   # honestly flagged
          "note": str | None
        }
    """
    target = profile.get("target_schools", "") or ""
    entries = target_school_entries(target)
    all_named = [n.strip() for n in target.split(",") if n.strip()]
    curated_names_lower = {e["name"].lower() for e in entries}
    # a named school is "uncurated" if it didn't resolve to a KB entry
    uncurated = []
    for n in all_named:
        e = lookup_school(n)
        if not e:
            uncurated.append(n)

    note = None
    if uncurated and not entries:
        note = (
            f"We don't have a detailed, source-verified profile for "
            f"{', '.join(uncurated)} yet, so guidance for those is general. "
            "The universal rule still holds: depth beats breadth - one genuine "
            "spike and a concrete achievement outweigh a long, shallow activity "
            "list at any selective school."
        )
    elif uncurated:
        note = (
            f"Detailed profiles shown below are source-verified. We don't have "
            f"one for {', '.join(uncurated)} yet - treat guidance for those as general."
        )

    return {
        "schools": entries,
        "uncurated": uncurated,
        "note": note,
    }


def _roadmap_anchor(target_schools: str):
    """The KB anchor for a roadmap: the most selective (reach) matched
    school, which sets the bar. Mirrors the frontend."""
    entries = target_school_entries(target_schools)
    if not entries:
        return None, entries
    ordered = sorted(entries, key=lambda s: 0 if s.get("tier") == "reach" else 1)
    return ordered[0], entries


def generate_admissions_roadmap(profile: dict, top_opportunity: dict | None = None) -> dict:
    """School-aware admissions roadmap, server-side mirror of the frontend
    generateAdmissionsRoadmapLocal. Branches US-holistic vs UK-course-specific
    on the anchor school, weaves in the anchor's real KB values / accepted
    pattern, respects the dataDepth honesty flag, and flags mixed US+UK lists.

    Returns {'summary': str, 'milestones': [ {stage,title,description,
    success_criteria,estimated_timeframe,first_action,resource,risk,...}, ]}.
    Deterministic and honest - no fabricated per-school tactics.
    """
    major = profile.get("intended_major") or "your intended field"
    grade = profile.get("grade_level") or "your current grade"
    schools = [s.strip() for s in (profile.get("target_schools") or "").split(",") if s.strip()]
    top_school = schools[0] if schools else "your target schools"

    anchor, kb = _roadmap_anchor(profile.get("target_schools", ""))
    any_uk = any(s.get("country") == "UK" for s in kb)
    is_uk = (anchor.get("country") == "UK") if anchor else any_uk

    blob = ""
    if anchor:
        blob = (anchor.get("guidance", "") + " " + anchor.get("acceptedPattern", "") + " " + " ".join(anchor.get("values", []))).lower()
    is_portfolio = "portfolio" in blob
    is_audition = "audition" in blob
    is_maker = any(w in blob for w in ("maker", "build", "hands-on making", "tinker"))
    is_general = bool(anchor) and anchor.get("dataDepth") == "general"
    two_values = " and ".join(anchor.get("values", [])[:2]) if anchor else ""
    import re as _re
    evidence = ""
    if anchor and not is_general:
        evidence = _re.sub(r"^By [^,]+,\s*", "", anchor.get("acceptedPattern", ""))
        evidence = _re.sub(r"^Public analyses[^:]*:\s*", "", evidence)

    opp_line = (
        f'Your current top-matched opportunity is "{top_opportunity["title"]}" ({top_opportunity.get("pct","")}% fit) - a strong place to start.'
        if top_opportunity else
        "Check the Opportunities page first so this points at a real opportunity instead of a placeholder."
    )
    opp_action = (
        f'Today: open "{top_opportunity["title"]}" on your Opportunities page and note its real deadline.'
        if top_opportunity else
        f"Today: open the Opportunities page and shortlist two activities that fit {major}."
    )

    steps = []
    if is_uk:
        focus = (f"For {anchor['name']}, admissions is almost entirely about academic ability and genuine engagement with {major} - not a broad activity list."
                 if anchor else
                 f"UK admissions is almost entirely about academic ability and genuine engagement with your chosen subject - not a broad activity list.")
        steps.append({
            "title": f"Lock in top grades in the subjects {major} requires",
            "description": f"{focus} UK offers are built on predicted and achieved grades in specific subjects, so confirm the exact grade/subject requirements for {major} on each course page - they differ by university and course.",
            "success_criteria": f"You know the exact grade/subject requirements for {major} at each target university, and your predicted grades meet or beat them.",
            "estimated_timeframe": "Ongoing, checkpoint this month",
            "first_action": f"Today: look up the entry requirements for {major} at {top_school} and write down the exact grades and required subjects.",
            "resource": "Each university's official course page (requirements vary by course).",
            "risk": "Assuming a headline grade applies everywhere - requirements and required subjects vary sharply by course, and top programmes are far more demanding than a university's overall profile.",
        })
        steps.append({
            "title": "Go deep beyond the syllabus (super-curricular work)",
            "description": (f"{evidence} " if evidence else "") + f"UK tutors want evidence you engage with {major} above and beyond school: wider reading, lectures, MOOCs, essays, or a personal investigation. This - not a long CV of clubs - is what makes a personal statement stand out." + (f" It's exactly what {anchor['name']} means by valuing {two_values}." if anchor else ""),
            "success_criteria": f"You have a running list of subject-specific reading/projects you've genuinely engaged with and can discuss.",
            "estimated_timeframe": "2-4 months, ongoing",
            "first_action": f"Today: pick one book, paper, or online lecture in {major} beyond your school syllabus and start it this week.",
            "resource": "Reading lists from the university department pages; your Opportunities page for subject competitions.",
            "risk": "Listing activities without engaging - tutors probe what you actually learned, so depth of understanding beats a long list.",
        })
        steps.append({
            "title": "Prepare for any required admissions test",
            "description": (f"Many competitive UK courses (maths, economics, sciences, medicine, Oxbridge) require an admissions test - e.g. TMUA, ESAT, MAT, STEP, LNAT, or UCAT. " + (f"Check whether {anchor['name']} requires one for {major}. " if anchor else f"Check whether your courses require one for {major}. ") + "These differentiate near-identical top-grade applicants and need dedicated practice."),
            "success_criteria": "You know which admissions test(s), if any, your courses require, and have a practice plan or confirmed there are none.",
            "estimated_timeframe": "2-3 months before the test",
            "first_action": "Today: check each course page for an admissions-test requirement and note the registration deadline (these are strict).",
            "resource": "Official past papers for the relevant test; your Schedule page to block practice sessions.",
            "risk": "Missing the separate test-registration deadline - it is often earlier than the UCAS deadline and easy to overlook.",
        })
        steps.append({
            "title": "Add one subject-linked achievement or experience",
            "description": f"{opp_line} A subject essay competition, an olympiad, a relevant project, or (for vocational courses) real work experience gives concrete evidence of commitment to {major}. " + ("For your creative course, this means building your portfolio - the single most important element." if is_portfolio else "For your conservatoire audition, this means preparing your repertoire to the exact requirements." if is_audition else "Keep it genuinely tied to the subject."),
            "success_criteria": ("You have a growing portfolio showing process and ideas, not just finished pieces." if is_portfolio else "You have your audition repertoire chosen and in serious preparation." if is_audition else f"You have entered one subject competition or secured one relevant experience in {major}."),
            "estimated_timeframe": "2-4 months",
            "first_action": ("Today: shortlist three pieces for your portfolio and note what each demonstrates." if is_portfolio else opp_action),
            "resource": "Your Opportunities and Schedule pages; the course page for portfolio/audition requirements.",
            "risk": "Chasing prestige over subject-relevance - a modest but genuinely subject-linked achievement reads stronger than an impressive but unrelated one.",
        })
        no_interview = anchor and any(p in blob for p in ("doesn't interview", "does not interview", "no interview"))
        steps.append({
            "title": "Write a subject-focused UCAS personal statement and hit every deadline",
            "description": f"The UK personal statement (one statement for all five choices) should be overwhelmingly about {major}: why you want to study it, what you've done to explore it, and how you think. " + (f"{anchor['name']} doesn't interview, so the statement carries even more weight. " if no_interview else "") + "Track the UCAS deadline (15 October for Oxbridge/medicine/dentistry/vet; late January for most others) and any interview dates.",
            "success_criteria": "A subject-focused personal statement drafted, and every course's deadline (and any interview/test dates) on your Schedule.",
            "estimated_timeframe": "Application season",
            "first_action": f"Today: add the relevant UCAS deadline for your courses to your Schedule, and draft one paragraph on why you want to study {major}.",
            "resource": "Your Application workshop for the statement; your Schedule for deadlines.",
            "risk": 'Writing about personality or unrelated activities - UK tutors want academic substance, and generic "inspirational" openings or quotes count against you.',
            "if_it_works": "A genuinely academic, subject-obsessed statement plus strong grades and test scores is exactly what UK offers are built on.",
            "if_it_stalls": "If you're stretched, concentrate on grades and one deep super-curricular thread - those carry the most weight in the UK system.",
        })
    else:
        spike_risk = (f"Spreading across many unrelated activities - a focused profile reads far stronger to {anchor['name']} than a scattered one" + (f", which rewards {two_values}." if two_values else ".")
                      if anchor else
                      "Spreading across many unrelated activities - a focused profile reads far stronger than a scattered one.")
        steps.append({
            "title": f'Sharpen your "spike" in {major}',
            "description": f'Selective US admissions reward depth over breadth. Admissions officers look for a clear, demonstrated focus - a "spike" - in {major}.' + (f" {evidence}" if evidence else "") + " Naming yours focuses every stage after this.",
            "success_criteria": f"You can state, in one sentence, the specific angle within {major} you're known for.",
            "estimated_timeframe": "1-2 weeks",
            "first_action": f'Today: write one sentence finishing "I\'m the student who ______" about your focus in {major}.',
            "resource": "A teacher or mentor in the subject, as a sounding board.",
            "risk": spike_risk,
        })
        steps.append({
            "title": ("Build a signature project or portfolio" if is_maker else "Develop your creative portfolio" if is_portfolio else "Commit to one signature extracurricular"),
            "description": f"{opp_line} " + (f"Since {anchor['name'] if anchor else 'your target school'} values makers, the strongest thing you can do is build something tangible - a project, prototype, code, or competition entry - that shows hands-on ability, not just membership." if is_maker else "For your creative target, a portfolio that shows genuine process and voice is the backbone of your application." if is_portfolio else "One activity you go deep in - with real responsibility over time - beats five you barely touch. This is the backbone of your application."),
            "success_criteria": ("You have started one concrete project you can show and describe." if is_maker else "You have a portfolio in progress showing process, not just finished pieces." if is_portfolio else "You have joined (or founded) one activity you will stay committed to for at least a year."),
            "estimated_timeframe": "1 month to start, ongoing",
            "first_action": opp_action,
            "resource": "Your Opportunities page, filtered to your intended field.",
            "risk": "Chasing prestige over genuine fit - sustained, real involvement (or a real body of work) is what actually shows commitment.",
        })
        steps.append({
            "title": "Win a concrete, verifiable achievement",
            "description": f'A placement in a real competition, a published piece, or a measurable outcome turns "interested in {major}" into "demonstrated ability in {major}." This is the single highest-leverage credential you can add.',
            "success_criteria": "You have entered at least one competition or produced one concrete, external result.",
            "estimated_timeframe": "2-4 months",
            "first_action": "Today: pick one competition or award from your Opportunities page and put its deadline on your schedule.",
            "resource": "Your Schedule page, to work backward from the deadline into weekly prep.",
            "risk": "Preparing endlessly without ever entering - an actual entry, even without a win, is worth more than perpetual preparation.",
        })
        steps.append({
            "title": "Land hands-on experience (internship or research)",
            "description": "Real experience - a lab, an internship, a shadowing program - is what separates a strong applicant from a great one, and gives you specific stories for essays and interviews." + (f" {anchor['name']} particularly values genuine contribution to others, so experience that helps a community counts double here." if anchor and any(w in blob for w in ("service", "community", "leadership")) else ""),
            "success_criteria": "You have secured or applied to at least one internship, research, or shadowing opportunity.",
            "estimated_timeframe": "3-6 months",
            "first_action": "Today: draft a short, specific outreach email to one program or professor in your field.",
            "resource": "Your Application workshop, to draft and refine the outreach.",
            "risk": "Only applying to formal postings - a direct, specific email often opens doors that public listings never advertise.",
        })
        body_word = "body of work" if (is_maker or is_portfolio) else "activity"
        steps.append({
            "title": "Build your application and hit every deadline",
            "description": f"With a real spike, a signature {body_word}, an achievement, and experience, the final stage is execution: essays that tell your specific story" + (f" and speak to what {anchor['name']} actually values" if anchor else "") + f", and every deadline for {', '.join(schools[:3]) if schools else 'your schools'} tracked and met.",
            "success_criteria": "Every target school's deadline is on your schedule with a draft essay started for each.",
            "estimated_timeframe": "Application season",
            "first_action": "Today: add each target school's application deadline to your Schedule.",
            "resource": "Your Schedule and Application pages.",
            "risk": "Leaving essays to the last week - the strongest essays go through several honest revisions, which takes real lead time.",
            "if_it_works": "A focused, deadline-driven application to well-matched schools produces stronger outcomes than a rushed one to a longer list.",
            "if_it_stalls": "If you're overwhelmed, cut the school list to a realistic set anchored on genuine fit rather than name alone, and go deep on those.",
        })

    # Closing summary
    school_line = ""
    if anchor:
        if is_uk:
            school_line = f" Because {anchor['name']} decides on academic ability in {major} ({anchor['accept']}), this plan puts grades, subject depth, and any required test first - that is what UK offers actually turn on."
        elif anchor.get("tier") == "reach":
            school_line = f" Because {anchor['name']} is a genuine reach ({anchor['accept']}), strong grades and scores only get you considered - what this plan really builds is the depth and evidence that separate admits, especially {two_values}."
        else:
            school_line = f" {anchor['name']} ({anchor['accept']}) rewards a solid academic record plus a clear, demonstrated focus - this plan gives you both, which makes it a realistic and strong target."
        if is_general:
            school_line += f" (For {anchor['name']} we've verified the facts and admissions model; where school-specific admit detail is thin, this plan leans on what reliably works across similar schools.)"

    cross = ""
    has_us = any(s.get("country") == "US" for s in kb)
    has_uk = any(s.get("country") == "UK" for s in kb)
    if has_us and has_uk:
        cross = (" Note: your list also includes US schools, which are admitted holistically - they additionally want a \"spike,\" extracurricular depth, and personal essays, so budget separate time for that alongside this UK-focused plan."
                 if is_uk else
                 " Note: your list also includes UK schools, which are admitted on academic ability in one subject - they additionally want top grades, super-curricular depth, and (often) an admissions test rather than a broad activity list, so budget separate time for that alongside this US-focused plan.")

    throughline = (f"The honest throughline: UK admissions rewards demonstrated academic ability in {major} - top grades, genuine super-curricular depth, and (where required) admissions tests - far more than a broad activity list."
                   if is_uk else
                   "The honest throughline: depth beats breadth at every stage. One real spike, one concrete achievement, and real experience - tracked against real deadlines - matter far more than a long, shallow activity list.")
    summary = f"This plan moves from where you are in {grade} toward a standout application for {major}, in {len(steps)} stages. {throughline}{school_line}{cross}"

    return {
        "summary": summary,
        "milestones": [{**s, "stage": i + 1, "status": "planned"} for i, s in enumerate(steps)],
    }


def _admissions_shape(profile: dict) -> dict:
    """Shared admissions 'shape' for a profile - backend mirror of the frontend
    admissionsAnchor helper. Used by workshop/schedule-style generators so
    server-side advice matches the client."""
    anchor, kb = _roadmap_anchor(profile.get("target_schools", ""))
    blob = ""
    if anchor:
        blob = (anchor.get("guidance", "") + " " + anchor.get("acceptedPattern", "") + " " + " ".join(anchor.get("values", []))).lower()
    import re as _re
    return {
        "anchor": anchor, "kb": kb,
        "is_uk": (anchor.get("country") == "UK") if anchor else any(s.get("country") == "UK" for s in kb),
        "has_us": any(s.get("country") == "US" for s in kb),
        "has_uk": any(s.get("country") == "UK" for s in kb),
        "is_portfolio": "portfolio" in blob,
        "is_audition": "audition" in blob,
        "is_maker": any(w in blob for w in ("maker", "build", "hands-on making", "tinker")),
        "is_research": any(w in blob for w in ("research", "lab", "scholar")),
        "is_service": any(w in blob for w in ("service", "community", "leadership", "contribution")),
        "two_values": " and ".join(anchor.get("values", [])[:2]) if anchor else "",
    }


def admissions_deadline_context(profile: dict) -> list[str]:
    """School-aware application-deadline reminders for a student's target
    countries (real, well-known dates; no fabricated per-school specifics).
    Mirrors the frontend schedule banner."""
    s = _admissions_shape(profile)
    out = []
    if s["has_uk"]:
        out.append("UK / UCAS: 15 October deadline for Oxbridge, medicine, dentistry, and veterinary; late January for most other courses. Any required admissions test (TMUA, ESAT, MAT, STEP, LNAT, UCAT) has its own earlier registration deadline - check each course page.")
    if s["has_us"]:
        out.append("US: Early Decision / Early Action deadlines are usually 1 November (a binding ED offer often carries a meaningfully higher admit rate); Regular Decision usually 1 January. Rolling-admission schools reward applying early. Confirm each school's exact dates.")
    return out


def essay_structure(profile: dict, theme: str = "") -> dict:
    """School-aware application-essay scaffold - backend mirror of the workshop.
    Branches US personal-narrative vs UK subject-focused UCAS statement (the two
    are genuinely different shapes), weaving in the anchor's real values.
    Returns {'kind': 'uk'|'us', 'title': str, 'sections': [ {heading, guidance,
    prompt}, ], 'reminders': [str], 'cross_note': str}. Honest scaffolding only -
    never a written-for-you essay."""
    s = _admissions_shape(profile)
    major = profile.get("intended_major") or "your field"
    anchor_name = s["anchor"]["name"] if s["anchor"] else "your target schools"
    theme = theme or "[the story or trait you chose]"

    if s["is_uk"]:
        values_note = f" This is exactly what {anchor_name} means when it looks for {s['two_values']}." if s["anchor"] else ""
        mid_extra = (" Because your course is portfolio-based, your portfolio is the real centrepiece - reference the work and the thinking behind it."
                     if s["is_portfolio"] else
                     " Because your course is audition-based, your musical/performance development and repertoire are central here."
                     if s["is_audition"] else "")
        sections = [
            {"heading": "Why this subject (your motivation)",
             "guidance": f"A specific intellectual hook - an idea, problem, or question in {major} that genuinely grabbed you. Not 'I've always loved it', not a childhood story, not a quote.",
             "prompt": f"What specific idea or problem in {major} made you want to study it at degree level?"},
            {"heading": "What you've done to explore it (the bulk - super-curricular evidence)",
             "guidance": f"The heart of a UK statement: wider reading, lectures, MOOCs, projects, essays, competitions - and crucially, what you LEARNED or THOUGHT from each, not just that you did it.{values_note}{mid_extra}",
             "prompt": "Name 2-3 things you read or did beyond school, and one genuine idea or question each left you with."},
            {"heading": "Relevant skills & any super-curricular context (brief)",
             "guidance": f"Only what genuinely connects to studying {major}. Keep any extracurriculars short and tied back to academic qualities.",
             "prompt": f"What have you done that shows you can handle the academic demands of this course?"},
        ]
        reminders = [
            "Tutors probe what you actually understood - depth of thought beats a long list.",
            "Avoid personality essays, inspirational quotes, and generic openings; they count against you.",
            f"Every sentence should earn its place by showing academic engagement with {major}.",
        ]
        cross = ("You're also applying to US schools: they want the opposite - a personal, story-driven Common App essay about who you are. Write that separately; this structure is for your UK/UCAS statement only." if s["has_us"] else "")
        return {"kind": "uk", "title": f"UK personal-statement structure for {major}" + (f" (anchored on {anchor_name})" if s["anchor"] else ""),
                "sections": sections, "reminders": reminders, "cross_note": cross}
    else:
        values_tie = f" Where it fits honestly, let this connect to qualities {anchor_name} genuinely values - {s['two_values']} - shown through your story, never name-dropped." if s["anchor"] else ""
        sections = [
            {"heading": "Open in a specific moment (not a summary)",
             "guidance": "Start inside one concrete scene where this story happened - a single moment, with real detail. Avoid opening with a thesis or a quote.",
             "prompt": "What was the exact moment things shifted? Put the reader there."},
            {"heading": "The tension or turn",
             "guidance": "What was genuinely hard, uncertain, or surprising? Admissions officers connect with honesty here, not a highlight reel.",
             "prompt": "What did you get wrong first, or struggle with, before it worked?"},
            {"heading": "What you actually did",
             "guidance": "Concrete actions, in your own voice. Specifics over adjectives.",
             "prompt": "What are the 2-3 real things you did that you're proud of?"},
            {"heading": "What it changed in you",
             "guidance": f"The real reflection - how this shaped how you think, lead, or approach {major}. This is the heart of the essay.{values_tie}",
             "prompt": "How do you approach things differently now because of this?"},
            {"heading": "Close with forward motion",
             "guidance": "Tie it briefly to who you're becoming - without over-explaining or restating. Trust the story you told.",
             "prompt": ""},
        ]
        reminders = [
            "Write it yourself. A real, slightly imperfect voice beats a polished generic one every time.",
            "Cut anything that could appear in anyone's essay.",
            "Read it aloud - if it doesn't sound like you talking, revise it.",
        ]
        if s["has_uk"]:
            reminders.append("Your UK choices need a separate, subject-focused UCAS statement - this personal style does not fit them.")
        return {"kind": "us", "title": f"US application-essay structure for: {theme}" + (f" (anchored on {anchor_name})" if s["anchor"] else ""),
                "sections": sections, "reminders": reminders, "cross_note": ""}


def admissions_assistant_context(profile: dict) -> str:
    """School-aware system prompt for an admissions AI guide - backend mirror of
    the frontend admissionsMetisContext, so a server-side assistant (if ever
    wired to a route) gives the same school-specific, honest guidance. Never
    fabricates a school's requirements."""
    s = _admissions_shape(profile)
    major = profile.get("intended_major") or "their subject"
    ctx = ('You are Metis, the built-in ADMISSIONS guide inside "Kaidostar", helping a student build a strong '
           "university application. Be concise, practical, and honest. Never invent a school's specific "
           "requirements, deadlines, or statistics - if unsure, tell the student to verify on the official "
           "course/admissions page.\n\n")
    if profile.get("intended_major"):
        ctx += f'Student\'s intended major/subject: "{profile["intended_major"]}".\n'
    if profile.get("grade_level"):
        ctx += f'Current stage: {profile["grade_level"]}.\n'
    if profile.get("interests"):
        ctx += f'Their interests/background: "{profile["interests"]}".\n'
    if profile.get("student_achievements"):
        ctx += f'Achievements they\'ve stated: "{profile["student_achievements"]}".\n'
    if s["kb"]:
        ctx += "\nTarget schools (with what each actually rewards - use this to give school-specific advice):\n"
        for sc in s["kb"]:
            ctx += f"- {sc['name']} ({sc['country']}, {sc['tier']}, {sc['accept']}): values {', '.join((sc.get('values') or [])[:3])}."
            if sc.get("dataDepth") == "general":
                ctx += " [We have verified this school's facts and admissions model, but detailed admit-pattern data is limited - keep school-specific claims general and tell the student to confirm specifics.]"
            ctx += "\n"
        if s["is_uk"] and s["has_us"]:
            ctx += ("\nIMPORTANT: this student targets BOTH UK and US schools, which use fundamentally different models. "
                    "UK = academic ability in one subject (grades, super-curricular depth, admissions tests, a subject-focused "
                    "UCAS statement). US = holistic (a spike, extracurricular depth, leadership/impact, personal essays). "
                    "Advise on the right model for whichever school is asked about; they need separate preparation.\n")
        elif s["is_uk"]:
            uk_major = profile.get("intended_major") or "their subject"
            ctx += (f"\nThese are UK schools: admission is course-specific and academic. Steer the student toward top grades in the required "
                    f"subjects, genuine super-curricular depth in {uk_major}, any required admissions test, and a subject-focused "
                    f"UCAS personal statement - NOT a broad activity list or a US-style personal-narrative essay.\n")
        else:
            us_major = profile.get("intended_major") or "their field"
            ctx += (f'\nThese are US schools: admission is holistic. Steer the student toward a genuine "spike" in {us_major}, '
                    f"depth over breadth, a concrete achievement, real experience, and authentic personal essays that reflect what these schools value.\n")
    else:
        ctx += "\nThe student hasn't named target schools we have detailed data on yet - give sound general admissions advice and suggest adding target schools.\n"
    return ctx


# ============================================================================
# X-FACTOR: School Fit & Readiness (backend mirror of the frontend engine).
# Honest, evidence-based per-school readiness - never an admit probability.
# The evidence dict is supplied by the caller (the frontend has richer local
# signals like tracked events/roadmap progress; the backend accepts whatever
# the route can assemble from stored data, defaulting sensibly).
# ============================================================================

def _evidence_from_profile(profile: dict, signals: dict | None = None) -> dict:
    """Assemble the evidence counts a readiness score is built from. 'signals'
    lets a route pass real counts (achievements parsed, tracked events, roadmap
    progress); anything missing defaults to a safe zero/derived value."""
    signals = signals or {}
    ach = str(profile.get("student_achievements") or "").strip()
    import re as _re
    ach_items = [s.strip() for s in _re.split(r"[,;\n]+", ach) if len(s.strip()) > 2] if ach else []
    def _sig(key):
        # Robust: coerce any signal to a non-negative int, defaulting to 0.
        try:
            v = int(signals.get(key, 0) or 0)
            return v if v >= 0 else 0
        except (ValueError, TypeError):
            return 0
    done = _sig("done_stages")
    total = _sig("total_stages")
    if total and done > total:
        done = total  # never report more done than exist
    return {
        "ach_items": ach_items,
        "ach_count": len(ach_items),
        "tracked_count": _sig("tracked_count"),
        "event_count": _sig("event_count"),
        "competitions": _sig("competitions"),
        "internships": _sig("internships"),
        "done_stages": done,
        "total_stages": total,
        "has_major": bool((profile.get("intended_major") or "").strip()),
        "has_interests": bool((profile.get("interests") or "").strip()),
    }


def _parse_gpa(raw):
    """Parse a GPA string to a float on a 4.0 scale. Returns None if unusable.
    Accepts '3.8', '3.8/4.0', 'GPA 3.8'. Weighted GPAs >4.0 are clamped-flagged."""
    if not raw:
        return None
    import re as _re
    m = _re.search(r"(\d\.\d{1,2}|\d)", str(raw))
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    if v <= 0 or v > 5.5:
        return None
    return v


def _parse_test(raw):
    """Parse an SAT (400-1600) or ACT (1-36) score. Returns ('sat'|'act', value)
    or None. Recognizes the scale from the magnitude."""
    if not raw:
        return None
    import re as _re
    nums = [int(n) for n in _re.findall(r"\d{2,4}", str(raw))]
    for n in nums:
        if 400 <= n <= 1600:
            return ("sat", n)
    for n in nums:
        if 1 <= n <= 36:
            return ("act", n)
    return None


def academic_fit(school: dict, profile: dict) -> dict | None:
    """An HONEST academic-fit signal for one school, from the student's GPA and/or
    test scores against the school's SELECTIVITY (real accept rate / tier). Returns
    None if the student gave no academic data.

    Deliberately NOT a fake admit-probability. Admissions is holistic and we do
    not have real per-school GPA/SAT medians, so we give a calibrated,
    non-numeric read ('competitive' / 'in range, not sufficient alone' /
    'below the typical admitted range - a real headwind') tied to the school's
    own selectivity, always with the holistic caveat. This is the opposite of the
    vanity 'your 3.7 = 34% chance' claim competitors make.
    """
    gpa = _parse_gpa(profile.get("gpa"))
    test = _parse_test(profile.get("test_scores") or profile.get("gpa_test") or profile.get("test_score"))
    if gpa is None and test is None:
        return None

    # Selectivity band from the real accept rate string (e.g. '~3.6%').
    import re as _re
    acc_m = _re.search(r"([\d.]+)", str(school.get("accept", "")))
    # Guard the float parse: [\d.]+ can capture a malformed multi-dot run ("3.6.5")
    # or a lone ".", which float() rejects with ValueError. Curated school data is
    # clean today so this isn't hit in practice, but the sibling parsers
    # (_parse_gpa/_parse_test) and admissions_list_balance all guard this exact
    # parse - academic_fit was the lone unguarded one. Fail safe to "unknown accept".
    acc = None
    if acc_m:
        try:
            acc = float(acc_m.group(1))
        except ValueError:
            acc = None
    tier = school.get("tier")
    # Audition / portfolio schools (conservatoires, drama/music) admit on
    # performance, not GPA/test scores - a normal academic read misleads there.
    # Detect it honestly and say so instead of implying stats decide admission.
    _accept_text = str(school.get("accept", "")).lower()
    if "audition" in _accept_text or "portfolio" in _accept_text:
        _bits = []
        if gpa is not None:
            _bits.append(f"GPA {gpa:g}")
        if test is not None:
            _bits.append(f"{test[0].upper()} {test[1]}")
        return {
            "band": "audition-based",
            "stated": ", ".join(_bits),
            "note": ("This school admits primarily by audition or portfolio, not academic stats - "
                     "your GPA and test scores matter far less here than the quality of your "
                     "performance or work. Meet any academic minimum, then put your energy into "
                     "an outstanding audition or portfolio."),
        }
    # Bar rises as the school gets more selective. These are honest, widely-cited
    # rough floors for being *academically in the conversation* - NOT guarantees.
    if acc is not None and acc <= 10:
        gpa_strong, gpa_ok = 3.9, 3.7
        sat_strong, sat_ok = 1500, 1430
        act_strong, act_ok = 34, 32
        sel = "highly selective"
    elif (acc is not None and acc <= 25) or tier == "reach":
        gpa_strong, gpa_ok = 3.8, 3.5
        sat_strong, sat_ok = 1450, 1350
        act_strong, act_ok = 33, 30
        sel = "very selective"
    else:
        gpa_strong, gpa_ok = 3.6, 3.2
        sat_strong, sat_ok = 1350, 1200
        act_strong, act_ok = 29, 26
        sel = "selective"

    # Grade each provided metric.
    grades = []
    if gpa is not None:
        g = min(gpa, 4.0)  # treat weighted the same as capped for this rough read
        grades.append("strong" if g >= gpa_strong else ("ok" if g >= gpa_ok else "below"))
    if test is not None:
        kind, val = test
        strong = sat_strong if kind == "sat" else act_strong
        ok = sat_ok if kind == "sat" else act_ok
        grades.append("strong" if val >= strong else ("ok" if val >= ok else "below"))

    # Combine (worst-case honesty: if either metric is below, that's the headline).
    if "below" in grades:
        band = "headwind"
        note = (f"Your academic stats look below the typical admitted range for a {sel} school like this - "
                "a real headwind. It's not disqualifying (admissions is holistic), but the rest of your "
                "profile has to carry more weight, and this school likely belongs in your reach tier.")
    elif all(x == "strong" for x in grades):
        band = "competitive"
        note = (f"Your academic stats are competitive for a {sel} school - they clear the academic bar. "
                "That's necessary, not sufficient: at this selectivity, strong stats are common among "
                "applicants, so your activities, essays, and distinctiveness are what actually differentiate you.")
    else:
        band = "in-range"
        note = (f"Your academic stats are in a reasonable range for a {sel} school, but not a standout - "
                "they keep you in the conversation rather than lifting you above it. The holistic pieces "
                "(depth of activities, essays, fit) carry the decision from here.")

    label = []
    if gpa is not None:
        label.append(f"GPA {gpa:g}")
    if test is not None:
        label.append(f"{test[0].upper()} {test[1]}")
    return {"band": band, "note": note, "stated": ", ".join(label)}


def school_readiness(school: dict, profile: dict, ev: dict) -> dict:
    """Readiness for ONE school - backend mirror of the frontend schoolReadiness.
    Same scoring, same honest non-numeric bands, same school-model-specific
    next move."""
    is_uk = school.get("country") == "UK"
    tier = school.get("tier")
    general = school.get("dataDepth") == "general"

    score = 0
    factors = []
    if ev["has_major"]:
        score += 12
    if ev["has_interests"]:
        score += 6
    score += min(ev["ach_count"], 3) * 12
    if ev["ach_count"]:
        factors.append(f"{ev['ach_count']} stated achievement{'s' if ev['ach_count'] > 1 else ''}")
    score += min(ev["competitions"], 2) * 7
    score += min(ev["internships"], 2) * 8
    if ev["competitions"]:
        factors.append(f"{ev['competitions']} competition{'s' if ev['competitions'] > 1 else ''} tracked")
    if ev["internships"]:
        factors.append(f"{ev['internships']} internship/experience tracked")
    if ev["total_stages"]:
        score += round((ev["done_stages"] / ev["total_stages"]) * 16)
        if ev["done_stages"]:
            factors.append(f"{ev['done_stages']}/{ev['total_stages']} roadmap stages done")
    score += min(ev["tracked_count"], 3) * 2
    score = min(score, 100)

    reach = tier == "reach"
    accept = school.get("accept", "")
    if score < 25:
        band = "Getting started"
        note = (f"You're at the beginning for a school this selective ({accept}). That's completely normal - the plan below is how you build real signal."
                if reach else "You're at the beginning. The plan below builds the profile this school looks for.")
    elif score < 50:
        band = "Building"
        note = (f"You're building a foundation. For a reach like this ({accept}), keep concentrating on depth - one standout thread beats several shallow ones."
                if reach else "You're building a solid foundation for a realistic target here.")
    elif score < 72:
        band = "Competitive foundation" if reach else "Strong position"
        note = (f"You have a genuine foundation. At {accept}, nothing guarantees admission - but you're doing the right things; now deepen your strongest thread."
                if reach else "You're in a strong position for this school - keep the momentum and polish your application.")
    else:
        band = "Strong signal" if reach else "Excellent position"
        note = (f"You've built strong signal. Even so, at {accept} outcomes are never certain for anyone - focus now on telling your story well."
                if reach else "You're in an excellent position here - focus on execution and authentic essays.")

    major = profile.get("intended_major") or "your subject"
    values = school.get("values", []) or []
    if is_uk:
        if ev["ach_count"] == 0:
            move = f"Add one subject-linked achievement in {major} (an olympiad, essay competition, or EPQ) - UK tutors want demonstrated academic ability, and you have none logged yet."
        elif ev["done_stages"] < 2 and ev["total_stages"]:
            move = f"Go deeper beyond the syllabus in {major} (wider reading, a lecture series, a project) and log it - super-curricular depth is the heart of a UK personal statement."
        else:
            move = f"Confirm {school['name']}'s exact grade requirements and any admissions test for {major}, and start test prep - at {accept} this is what separates near-identical applicants."
        if not general and values:
            move += f" It particularly rewards {values[0]}."
    else:
        if ev["ach_count"] == 0:
            move = f'Win one concrete, verifiable achievement in {major} - it turns "interested" into "demonstrated," and you have none logged yet.'
        elif ev["internships"] == 0:
            move = f"Land one hands-on experience (research, internship, or shadowing) in {major} - it's what separates a strong applicant from a great one and gives real essay material."
        elif ev["done_stages"] < 3 and ev["total_stages"]:
            move = f'Deepen your signature "spike" in {major} rather than adding breadth - {school["name"]} rewards depth over a long activity list.'
        else:
            move = f"Focus on essays that speak to what {school['name']} genuinely values" + (f" - especially {' and '.join(values[:2])}" if values else "") + ", shown through your real story."

    return {"name": school["name"], "country": school.get("country"), "tier": tier,
            "accept": accept, "general": general, "score": score, "band": band,
            "band_note": note, "factors": factors, "next_move": move, "values": values[:3],
            "academic_fit": academic_fit(school, profile)}


def admissions_readiness(profile: dict, signals: dict | None = None) -> dict:
    """Readiness across all of a student's target schools (reach-first) - backend
    mirror of the frontend admissionsReadiness. Honest, evidence-based; the
    caller supplies real activity signals where available."""
    _, kb = _roadmap_anchor(profile.get("target_schools", ""))
    if not kb:
        return {"schools": [], "evidence": None}
    ev = _evidence_from_profile(profile, signals)
    schools = sorted(
        (school_readiness(s, profile, ev) for s in kb),
        key=lambda x: 0 if x["tier"] == "reach" else 1,
    )
    return {"schools": schools, "evidence": ev}


# ============================================================================
# UNIQUE #1: School List Balance Analyzer (backend mirror).
# ============================================================================
def admissions_list_balance(profile: dict, signals: dict | None = None) -> dict | None:
    """Is the student's list realistic? Classifies each school by verified tier
    refined by readiness, and returns an honest verdict on the list SHAPE plus
    the specific structural fix. Backend mirror of the frontend engine."""
    _, kb = _roadmap_anchor(profile.get("target_schools", ""))
    if not kb:
        return None
    ev = _evidence_from_profile(profile, signals)

    rd = []
    for s in kb:
        r = school_readiness(s, profile, ev)
        cat = "reach" if s.get("tier") == "reach" else "target"
        if cat == "target" and r["score"] < 35:
            cat = "reach"
        import re as _re
        accept_num = None
        m = _re.findall(r"[0-9.]+", str(s.get("accept", "")))
        if m:
            try:
                accept_num = float(m[0])
            except ValueError:
                accept_num = None
        if cat == "target" and r["score"] >= 60 and accept_num and accept_num >= 40:
            cat = "likely"
        rd.append({"name": s["name"], "country": s.get("country"), "tier": s.get("tier"),
                   "accept": s.get("accept"), "cat": cat, "score": r["score"]})

    reaches = [x for x in rd if x["cat"] == "reach"]
    targets = [x for x in rd if x["cat"] == "target"]
    likelies = [x for x in rd if x["cat"] == "likely"]
    n = len(rd)
    reach_share = len(reaches) / n if n else 0
    risk = None

    if n < 3:
        verdict = "Too short to judge"
        note = f"You've listed {n} school{'' if n == 1 else 's'}. A healthy list usually spans a few reaches, a few realistic targets, and at least one you'd be genuinely happy to attend and are very likely to get into."
    elif not likelies and not targets:
        verdict = "All reaches — high risk"
        note = "Every school on your list is a reach for you right now. Even a strong applicant can be shut out of an all-reach list, because at these admit rates outcomes are partly out of anyone's control."
        risk = "Add 2-3 schools you'd genuinely be happy to attend where your profile is comfortably above the bar - not as \"backups you'll resent,\" but as real options."
    elif not likelies:
        verdict = "Reach-heavy — add a floor"
        note = "You have realistic targets, but no school you're very likely to get into. That's the one gap that turns a good list into a risky one."
        risk = "Add at least one \"likely\" school - a place you'd be happy at where your readiness is strong and the admit rate is higher. It's the safety net that lets you aim high elsewhere without fear."
    elif reach_share > 0.7:
        verdict = "Aiming very high"
        note = "Most of your list is reaches, but you do have a floor. That's an aggressive-but-defensible shape - just make sure the reaches are schools you genuinely fit, not just names."
        risk = "Consider swapping one reach for a strong target you're excited about - it raises your odds of a great outcome without lowering your ceiling much."
    elif not reaches:
        verdict = "Very safe — you can aim higher"
        note = "Your list has no genuine reaches. If there's a dream school you'd regret not trying for, your profile may support adding one - a well-chosen reach costs you little."
        risk = "Add one or two genuine reaches you'd love to attend. With your foundation, it's worth the shot."
    else:
        verdict = "Well balanced"
        note = "Your list spans reaches, realistic targets, and a floor you're likely to get into. This is the shape admissions counselors actually recommend - now the work is depth, not more schools."

    return {"counts": {"reach": len(reaches), "target": len(targets), "likely": len(likelies), "total": n},
            "schools": rd, "verdict": verdict, "verdict_note": note, "risk": risk}


# ============================================================================
# UNIQUE #2: Profile Gap Radar (backend mirror).
# ============================================================================
def admissions_gap_radar(profile: dict, signals: dict | None = None) -> dict | None:
    """The ONE addition that would strengthen the student's standing across the
    MOST of their target schools at once. Whole-picture optimization against
    their real profile. Backend mirror of the frontend engine."""
    _, kb = _roadmap_anchor(profile.get("target_schools", ""))
    if not kb:
        return None
    ev = _evidence_from_profile(profile, signals)
    major = profile.get("intended_major") or "your field"
    any_uk = any(s.get("country") == "UK" for s in kb)
    any_us = any(s.get("country") == "US" for s in kb)
    total = len(kb)
    candidates = []

    if ev["ach_count"] == 0:
        candidates.append({
            "key": "achievement",
            "move": (f"Win or place in one subject competition/olympiad in {major}" if any_uk
                     else f"Win one concrete, verifiable achievement in {major} (a competition placement, a published piece, a measurable result)"),
            "why": f'Turns "interested in {major}" into "demonstrated ability" - the single highest-signal thing you can add, and it strengthens EVERY school on your list.',
            "lifts": total, "missing": True})
    if ev["done_stages"] < 2:
        candidates.append({
            "key": "depth",
            "move": (f"Build genuine super-curricular depth in {major} (wider reading, a lecture series, a self-driven project) and document what you learned" if any_uk
                     else f'Deepen ONE signature "spike" in {major} rather than adding breadth'),
            "why": ("UK tutors read for demonstrated engagement beyond the syllabus - it's the heart of a strong personal statement across all your UK choices." if any_uk
                    else "Selective US schools reward depth over a long activity list - one deep thread lifts every holistic school you're applying to."),
            "lifts": total, "missing": True})
    if ev["internships"] == 0:
        us_count = len([s for s in kb if s.get("country") == "US"])
        candidates.append({
            "key": "experience",
            "move": f"Land one hands-on experience in {major} - research, an internship, or shadowing",
            "why": ("Real experience separates strong applicants from great ones at holistic schools, and gives you concrete, un-fakeable material for essays and interviews." if any_us
                    else "Relevant experience or a research project gives your application specific, credible substance."),
            "lifts": (max(us_count, -(-total // 2)) if any_us else -(-total // 2)), "missing": True})
    if any_uk:
        candidates.append({
            "key": "test",
            "move": f"Confirm and prepare for any required admissions test (TMUA, ESAT, MAT, STEP, LNAT, or UCAT) for {major}",
            "why": "For competitive UK courses the admissions test is a genuine differentiator among near-identical top-grade applicants - and registration deadlines come early.",
            "lifts": len([s for s in kb if s.get("country") == "UK"]), "missing": True})

    if not candidates:
        return {"top": None,
                "note": "You've already logged the big signals (an achievement, real depth, and experience). At this point the highest-leverage work isn't adding more - it's telling your story well in essays and hitting every deadline.",
                "candidates": []}

    candidates.sort(key=lambda c: c["lifts"], reverse=True)
    return {"top": candidates[0],
            "note": f"Across your {total} target school{'s' if total > 1 else ''}, this single move would strengthen your standing at the most of them at once.",
            "candidates": candidates}


# ============================================================================
# THE UNIQUE ONE: Trajectory engine (backend mirror).
# The backend stores snapshots in the admissions_snapshots table; these pure
# functions compute the momentum read from a list of snapshot dicts, matching
# the frontend admissionsTrajectory exactly. Snapshots are the student's own
# real evidence at real timestamps - the trajectory read is descriptive of what
# changed, never a fabricated forecast.
# ============================================================================

def _runway_months(profile: dict):
    """Rough application runway in months from grade level - honest context for
    pace, never a hard deadline. Mirrors the frontend."""
    import re as _re
    g = str(profile.get("grade_level") or "").lower()
    if _re.search(r"(^|\D)(12|senior|year 13|yr 13|upper sixth)(\D|$)", g):
        return 3
    if _re.search(r"(^|\D)(11|junior|year 12|yr 12|lower sixth)(\D|$)", g):
        return 12
    if _re.search(r"(^|\D)(10|sophomore|year 11|yr 11)(\D|$)", g):
        return 24
    if _re.search(r"(^|\D)(9|freshman|year 10|yr 10)(\D|$)", g):
        return 36
    return None


def build_readiness_snapshot(profile: dict, signals: dict | None = None) -> dict | None:
    """Compute a fresh readiness snapshot dict (to persist). Returns None if the
    student has no target schools we have data on."""
    r = admissions_readiness(profile, signals)
    if not r["schools"]:
        return None
    ev = r["evidence"] or {}
    avg = round(sum(s["score"] for s in r["schools"]) / len(r["schools"]))
    return {
        "avg": avg,
        "per_school": [{"name": s["name"], "score": s["score"], "band": s["band"]} for s in r["schools"]],
        "evidence": {
            "ach_count": ev.get("ach_count", 0), "competitions": ev.get("competitions", 0),
            "internships": ev.get("internships", 0), "done_stages": ev.get("done_stages", 0),
            "total_stages": ev.get("total_stages", 0), "event_count": ev.get("event_count", 0),
        },
    }


def compute_trajectory(snapshots: list[dict], profile: dict) -> dict:
    """The momentum read from an ordered (oldest-first) list of snapshot dicts,
    each with keys: created_at (iso str), avg (int), evidence (dict). Backend
    mirror of the frontend admissionsTrajectory."""
    from datetime import datetime, timezone
    runway = _runway_months(profile)

    def _ts(s):
        v = s.get("created_at") or s.get("ts")
        if isinstance(v, datetime):
            return v
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except Exception:
            return datetime.now(timezone.utc)

    # Robust: guarantee every snapshot has a numeric avg (malformed stored rows).
    for _s in snapshots:
        try:
            _s["avg"] = int(_s.get("avg", 0) or 0)
        except (ValueError, TypeError):
            _s["avg"] = 0
    n = len(snapshots)
    if n < 2:
        return {
            "state": "baseline",
            "headline": "Your starting point is recorded." if n == 1 else "Building your baseline.",
            "detail": "Come back as you make progress - this will track how your readiness actually moves over time, which is something no one-time answer can show you. Log an achievement or complete a roadmap stage and watch it respond.",
            "points": [{"ts": str(s.get("created_at") or s.get("ts")), "avg": s.get("avg", 0)} for s in snapshots],
            "runway_months": runway, "delta": 0, "span_days": 0,
        }

    first, last = snapshots[0], snapshots[-1]
    recent = snapshots[max(0, n - 4)]
    delta = last["avg"] - recent["avg"]
    total_delta = last["avg"] - first["avg"]
    now = datetime.now(timezone.utc)
    t_last = _ts(last)
    if t_last.tzinfo is None:
        t_last = t_last.replace(tzinfo=timezone.utc)
    span_days = max(1, round((_ts(last) - _ts(first)).total_seconds() / 86400))
    days_since_move = round((now - t_last).total_seconds() / 86400)

    biggest_jump, jump_what, jump_when = 0, None, None
    for k in range(1, n):
        d = snapshots[k]["avg"] - snapshots[k - 1]["avg"]
        if d > biggest_jump:
            biggest_jump = d
            a, prev = snapshots[k].get("evidence", {}), snapshots[k - 1].get("evidence", {})
            if a.get("ach_count", 0) > prev.get("ach_count", 0):
                jump_what = "logging a new achievement"
            elif a.get("internships", 0) > prev.get("internships", 0):
                jump_what = "adding hands-on experience"
            elif a.get("competitions", 0) > prev.get("competitions", 0):
                jump_what = "entering a competition"
            elif a.get("done_stages", 0) > prev.get("done_stages", 0):
                jump_what = "completing roadmap stages"
            else:
                jump_what = "your logged progress"
            jump_when = str(snapshots[k].get("created_at") or snapshots[k].get("ts"))

    if delta >= 6:
        state = "rising"
        headline = f"Your readiness is climbing — up {delta} points recently."
        detail = (f"The biggest jump came from {jump_what}. Keep doing exactly that kind of concrete, evidence-building work - it's what's moving your standing."
                  if biggest_jump > 0 and jump_what else "You're building real, measurable momentum. Keep the concrete work going.")
    elif delta <= -4:
        state = "declining"
        headline = "Your relative standing has slipped a little."
        detail = "This usually means the calendar is moving while new evidence isn't being added. The fix is one concrete action - log an achievement, complete a roadmap stage, or track a new opportunity."
    elif days_since_move >= 21:
        state = "stalled"
        headline = f"Momentum has stalled — {days_since_move} days since your last logged progress."
        detail = (f"With roughly {runway} month{'' if runway == 1 else 's'} of runway left, consistent small steps beat occasional big pushes. Pick one thing from your #1 move and do it this week."
                  if runway else "Consistent small steps beat occasional big pushes. Pick one thing from your #1 move and do it this week.")
    else:
        state = "steady"
        headline = (f"Steady progress — up {total_delta} points over {span_days} day{'' if span_days == 1 else 's'}."
                    if total_delta > 0 else "Holding steady.")
        detail = "You're moving at a consistent pace. The students who end up with the strongest applications are the ones who keep this rhythm up over months, not the ones who cram."

    pace_note = None
    if runway is not None:
        if runway <= 3 and last["avg"] < 45:
            pace_note = "You're close to application season and still building - focus now on finishing what you've started and telling your story well, rather than starting new long projects."
        elif runway >= 12 and total_delta > 0:
            pace_note = f"You have real runway ({runway}+ months). At your current pace you have plenty of time to build a genuinely deep profile - the advantage of starting early is compounding, so keep going."

    return {
        "state": state, "headline": headline, "detail": detail, "pace_note": pace_note,
        "delta": delta, "total_delta": total_delta, "span_days": span_days, "days_since_move": days_since_move,
        "biggest_jump": biggest_jump, "jump_what": jump_what, "jump_when": jump_when,
        "runway_months": runway,
        "points": [{"ts": str(s.get("created_at") or s.get("ts")), "avg": s.get("avg", 0)} for s in snapshots],
        "current": last["avg"],
    }


# ============================================================================
# X-FACTOR DEEPENED (backend mirror): milestones, consistency, weekly focus.
# Milestones are derived from the persisted snapshot series (no separate table
# needed - they're a pure function of the trajectory), so the backend can return
# the same "journey so far" the frontend shows. Consistency and weekly focus are
# pure reads over snapshots + the live gap-radar.
# ============================================================================

def derive_milestones(snapshots: list[dict]) -> list[dict]:
    """Reconstruct the ordered list of milestone moments from the full snapshot
    series (oldest-first). Pure and deterministic - mirrors the cumulative effect
    of the frontend detectAdmissionsMilestones run across the history."""
    ms = []
    seen = set()
    def add(key, ts, icon, title, detail):
        if key not in seen:
            seen.add(key)
            ms.append({"key": key, "ts": str(ts), "icon": icon, "title": title, "detail": detail})

    if not snapshots:
        return ms
    first = snapshots[0]
    add("started", first.get("created_at") or first.get("ts"), "flag",
        "You started your journey", "Your baseline is recorded. Everything from here is forward motion.")

    def band_of(v):
        return 0 if v < 25 else 1 if v < 50 else 2 if v < 72 else 3
    names = ["Getting started", "Building", "Competitive foundation", "Strong signal"]

    for k in range(1, len(snapshots)):
        prev, cur = snapshots[k - 1], snapshots[k]
        pe, ce = prev.get("evidence", {}) or {}, cur.get("evidence", {}) or {}
        ts = cur.get("created_at") or cur.get("ts")
        if (pe.get("ach_count", 0)) == 0 and (ce.get("ach_count", 0)) > 0:
            add("first_achievement", ts, "trophy", "First achievement logged", 'You turned "interested" into "demonstrated." This is the highest-signal thing on any application.')
        if (pe.get("internships", 0)) == 0 and (ce.get("internships", 0)) > 0:
            add("first_experience", ts, "briefcase", "First hands-on experience", "Real experience is what separates a strong applicant from a great one - and it gives you genuine essay material.")
        if (pe.get("competitions", 0)) == 0 and (ce.get("competitions", 0)) > 0:
            add("first_competition", ts, "medal", "First competition entered", "Entering matters more than winning - you now have a concrete, verifiable credential in progress.")
        pb, cb = band_of(prev["avg"]), band_of(cur["avg"])
        if cb > pb:
            add("band_" + str(cb), ts, "rise", 'Readiness reached "' + names[cb] + '"', "Your overall signal crossed into a new tier. Concrete, sustained work is paying off.")
        if ce.get("total_stages") and (ce.get("done_stages", 0)) >= ce["total_stages"] and (pe.get("done_stages", 0)) < ce["total_stages"]:
            add("roadmap_complete", ts, "star", "Roadmap complete", "You finished every stage of your plan. Now it is all about execution and telling your story well.")
        elif (ce.get("done_stages", 0)) >= 3 and (pe.get("done_stages", 0)) < 3:
            add("roadmap_momentum", ts, "check", "Three roadmap stages done", "You are past the hardest part - starting. Consistency from here is what wins.")

    return ms[-60:]


def compute_consistency(snapshots: list[dict]) -> dict:
    """How many of the last 6 weeks had logged activity, plus current streak.
    Mirrors the frontend admissionsConsistency."""
    from datetime import datetime, timezone
    if len(snapshots) < 2:
        return {"active_weeks": 0, "window_weeks": 6, "streak_weeks": 0, "note": None}

    def _ts(s):
        v = s.get("created_at") or s.get("ts")
        if isinstance(v, datetime):
            return v
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except Exception:
            return datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)
    window = 6
    active = set()
    for k in range(1, len(snapshots)):
        if (snapshots[k].get("evidence") or {}) == (snapshots[k - 1].get("evidence") or {}):
            continue
        t = _ts(snapshots[k])
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        wk = int((now - t).total_seconds() // (7 * 86400))
        if 0 <= wk < window:
            active.add(wk)
    streak = 0
    for w in range(window):
        if w in active:
            streak += 1
        elif w > 0:
            break
    active_weeks = len(active)
    note = None
    if streak >= 3:
        note = f"You've made progress {streak} weeks running - that consistency is exactly what builds a standout profile."
    elif active_weeks >= 3:
        note = f"You've been active {active_weeks} of the last {window} weeks. Steady beats sporadic."
    elif active_weeks >= 1:
        note = "You've logged progress recently - build it into a weekly rhythm and it compounds."
    return {"active_weeks": active_weeks, "window_weeks": window, "streak_weeks": streak, "note": note}


def weekly_focus(profile: dict, snapshots: list[dict], signals: dict | None = None) -> dict | None:
    """The single adaptive weekly recommendation, framed by momentum. Mirrors the
    frontend admissionsWeeklyFocus. Takes the snapshot series so it can read the
    trajectory state."""
    gap = admissions_gap_radar(profile, signals)
    if not gap:
        return None
    traj = compute_trajectory(snapshots, profile)
    core = gap["top"]["move"] if gap.get("top") else None
    state = traj.get("state")
    if not core:
        return {"move": "Draft one real essay paragraph this week",
                "why": "You've logged the big signals already. This week, open your Application workshop and draft one paragraph of a real essay - execution is now your highest-leverage work.",
                "momentum": state, "from_history": True}
    low = core[0].lower() + core[1:]
    if state == "rising":
        jw = traj.get("jump_what")
        why = f"You've got real momentum right now{(' (that came from ' + jw + ')') if jw else ''} - the best time to push is when you're already moving. This week: {low}."
    elif state in ("stalled", "declining"):
        why = f"It's been a quiet stretch, and the calendar doesn't pause. One concrete action restarts everything. This week, just this: {low}."
    elif state == "steady":
        why = f"You're in a good rhythm. Keep it going with the single move that helps the most schools at once. This week: {low}."
    else:
        why = f"Your highest-leverage move to start with: {low}."
    return {"move": core, "why": why, "lifts": gap["top"]["lifts"] if gap.get("top") else None,
            "momentum": state, "from_history": len(snapshots) >= 2}


# ============================================================================
# HONEST HUMANIZER (backend mirror): analyze the student's OWN essay draft.
# Flags clichés, AI-tells, vague words, repeated openers, and school-format
# misfit - concrete revision feedback, never a rewrite, never detector evasion.
# Mirrors the frontend polishAnalyze.
# ============================================================================

ESSAY_CLICHES = [
    "ever since i was young", "ever since i was a child", "from a young age", "for as long as i can remember",
    "changed my life", "changed me forever", "little did i know", "taught me the true meaning",
    "the true meaning of", "made me who i am today", "shaped me into", "i realized that", "i learned that",
    "step out of my comfort zone", "outside my comfort zone", "comfort zone", "hard work and dedication",
    "passion for", "my passion", "i am passionate about", "open my eyes", "opened my eyes", "eye-opening",
    "in today's society", "in todays society", "in this day and age", "the world we live in",
    "make a difference", "give back to my community", "well-rounded", "think outside the box",
    "against all odds", "light at the end of the tunnel", "journey", "my journey", "rollercoaster",
    "blood, sweat, and tears", "last but not least", "in conclusion", "all walks of life",
]
AI_TELLS = [
    "moreover", "furthermore", "in addition to this", "it is important to note", "it is worth noting",
    "delve into", "delving into", "navigate the complexities", "navigating the complexities", "tapestry",
    "testament to", "a testament", "underscores", "fostering", "foster a", "showcase", "showcasing",
    "multifaceted", "holistic", "myriad", "plethora", "pivotal", "pivotal role", "crucial role",
    "in the realm of", "realm of", "landscape of", "the landscape", "ever-evolving", "ever-changing",
    "not only", "but also", "seamless", "seamlessly", "robust", "leverage", "leveraging", "cutting-edge",
    "first and foremost", "when it comes to", "at the end of the day", "embark on", "embark",
]
VAGUE_WORDS = ["very", "really", "things", "stuff", "a lot", "many things", "various", "numerous",
               "several", "amazing", "incredible", "awesome", "great", "good", "nice", "interesting",
               "important", "impactful", "meaningful", "unique", "special"]


def _essay_find(lower_text: str, phrases: list[str]) -> list[dict]:
    import re as _re
    hits = []
    for p in phrases:
        pat = "(^|[^a-z])" + _re.escape(p) + "([^a-z]|$)"
        c = len(_re.findall(pat, lower_text))
        if c > 0:
            hits.append({"phrase": p, "count": min(c, 3)})
    return hits


def polish_analyze(text: str, profile: dict) -> str:
    """Feedback on the student's OWN draft - mirror of the frontend polishAnalyze.
    Concrete, do-it-yourself revision notes; never rewrites, never evades
    detection."""
    import re as _re
    lower = text.lower()
    words = _re.findall(r"\b[\w']+\b", text)
    word_count = len(words)
    sentences = [s for s in _re.split(r"(?<=[.!?])\s+", text) if s.strip()]

    cliches = _essay_find(lower, ESSAY_CLICHES)
    ai_tells = _essay_find(lower, AI_TELLS)
    vague = _essay_find(lower, VAGUE_WORDS)

    openers = {}
    for s in sentences:
        parts = s.strip().split()
        first = (parts[0].lower().strip("^a-z") if parts else "")
        first = _re.sub(r"[^a-z']", "", parts[0].lower()) if parts else ""
        if first:
            openers[first] = openers.get(first, 0) + 1
    repeated = sorted([(w, c) for w, c in openers.items() if c >= 3 and len(w) > 1], key=lambda x: -x[1])

    i_start = len([s for s in sentences if _re.match(r"^i\b", s.strip().lower())])
    numbers = len(_re.findall(r"\b\d+\b", text))

    r = f"DRAFT CHECK — feedback on YOUR writing ({word_count} words, {len(sentences)} sentences)\n"
    r += "The point of this is to help you revise it yourself. Nothing here rewrites your essay for you.\n"

    flags = len(cliches) + len(ai_tells)
    if flags == 0 and len(vague) <= 2:
        voice = "STRONG: this reads specific and personal. Keep going."
    elif flags <= 2:
        voice = "GOOD, with a few spots to sharpen below."
    elif flags <= 5:
        voice = "GENERIC IN PLACES: several phrases below appear in thousands of essays - swapping them for your specifics will make it unmistakably yours."
    else:
        voice = "READS GENERIC / AI-LIKE: a lot of the phrasing below is the kind admissions readers see constantly. This needs your real, specific voice - the notes show exactly where."
    r += f"\nOverall: {voice}\n"

    if cliches:
        r += f"\n① ADMISSIONS CLICHÉS ({len(cliches)}) — every reader has seen these; replace with your specifics:\n"
        for h in cliches[:8]:
            r += f'   • "{h["phrase"]}"' + (f' (×{h["count"]})' if h["count"] > 1 else "") + "\n"
    if ai_tells:
        r += f"\n② AI-TELL PHRASES ({len(ai_tells)}) — these words make writing sound machine-generated; cut or replace:\n"
        for h in ai_tells[:8]:
            r += f'   • "{h["phrase"]}"' + (f' (×{h["count"]})' if h["count"] > 1 else "") + "\n"
    if vague:
        r += f"\n③ VAGUE WORDS ({len(vague)}) — swap each for a concrete detail (\"very hard\" → what exactly?):\n"
        r += "   " + ", ".join('"' + h["phrase"] + '"' for h in vague[:10]) + "\n"
    if repeated:
        r += "\n④ REPEATED SENTENCE OPENERS — vary these so it doesn't read like a list:\n"
        for w, c in repeated[:4]:
            r += f'   • {c} sentences start with "{w.capitalize()}..."\n'
    if i_start >= max(4, -(-len(sentences) // 2)):
        r += f'\n⑤ "I"-HEAVY — {i_start} of {len(sentences)} sentences start with "I". Some is fine in a personal essay, but vary the rhythm so a few sentences lead with action or detail instead.\n'
    if numbers == 0 and word_count > 150:
        r += "\n⑥ NO CONCRETE NUMBERS — specifics (how many, how long, how much) make a story credible and vivid. Where could one real number go?\n"

    shape = _admissions_shape(profile)
    if shape["is_uk"]:
        major = profile.get("intended_major") or "your subject"
        personal_open = bool(_re.match(r"^(i |ever since|from a young|for as long|when i was|growing up)", text.strip().lower()))
        r += f"\n⑦ FORMAT CHECK (UK) — your targets are UK universities. A UCAS statement should be ~80% about {major}: what you've read, explored, and understood, not a personal narrative."
        if personal_open:
            r += f" Your opening reads personal/narrative - for the UK, lead with a specific idea or question in {major} instead."
        r += "\n"
    elif shape["anchor"]:
        r += f"\n⑦ FORMAT CHECK (US) — good: US personal essays SHOULD be story-driven and personal like this. Make sure the reflection connects to who you are, and (where honest) to what {shape['anchor']['name']} values.\n"

    if not cliches and not ai_tells and not vague and not repeated:
        r += "\nNo major red flags found - this already reads specific and human. Final pass: read it aloud, and cut any sentence that doesn't earn its place.\n"
    r += "\nRemember: the strongest essays are honest and specific, not polished-and-generic. Revise in your own voice - that's what actually stands out."
    return r


def brainstorm_outline(profile: dict, answers: dict) -> dict:
    """Assemble the student's OWN answers into a personal essay outline - mirror
    of the frontend brainstorm generator. Never invents content; every line is
    the student's material, organized. Returns {'ok': bool, 'outline': str}."""
    moment = (answers.get("moment") or "").strip()
    struggle = (answers.get("struggle") or "").strip()
    did = (answers.get("did") or "").strip()
    changed = (answers.get("changed") or "").strip()
    filled = sum(1 for x in (moment, struggle, did, changed) if x)
    if filled < 2:
        return {"ok": False, "outline": "Answer at least the first couple of questions - the outline is built entirely from your own words, so it needs your real material to work with."}

    shape = _admissions_shape(profile)
    major = profile.get("intended_major") or "your field"
    uk_note = ""
    if shape["is_uk"]:
        uk_note = f"\n\nNOTE: your target schools are UK - a UK personal statement should be ~80% about your subject, not a personal narrative. Use this story only if it genuinely shows academic engagement with {major}; otherwise switch to the UK essay format."

    o = "YOUR ESSAY OUTLINE — built entirely from your own answers\n(These are YOUR words, organized. Now write the full essay yourself, in your voice.)\n"
    o += f'\n1. OPEN HERE (drop the reader into this moment):\n   "{moment or "[the specific moment you described]"}"\n   → Write this as a scene, present and concrete. Don\'t explain it yet - let the reader be there.\n'
    if struggle:
        o += f'\n2. THE TENSION (what was hard/uncertain):\n   "{struggle}"\n   → Be honest here. This is where the reader leans in.\n'
    if did:
        o += f'\n3. WHAT YOU DID (your real, specific actions):\n   "{did}"\n   → Keep the specifics. Cut any adjective you could replace with a fact.\n'
    if changed:
        o += f'\n4. WHAT IT CHANGED (the heart of the essay):\n   "{changed}"\n   → This is the reflection that makes it matter. Connect it to who you\'re becoming, briefly.\n'
    o += f"\n5. CLOSE with forward motion - tie it to how you'll carry this into {major}, without over-explaining.\n"
    o += "\nHONEST CHECK before you write:\n- Could this exact story belong to anyone else? If yes, add the details that make it only yours.\n- Are you telling the reader how to feel, or showing them? Show.\n- Read your finished draft aloud - if it doesn't sound like you talking, it isn't done." + uk_note
    return {"ok": True, "outline": o}


# ============================================================================
# COMPETITIVE-GRADE ESSAY REVIEWER (backend mirror of essayRubricReview).
# Per-dimension scoring + the two differentiators competitors lack: grounding in
# the student's real profile, and alignment to the anchor school's values/format.
# Honest draft-strength read, never an admit predictor, never a rewrite.
# ============================================================================

def essay_rubric_review(text: str, profile: dict, prompt: str = "") -> dict:
    import re as _re
    lower = text.lower()
    words = _re.findall(r"\b[\w']+\b", text)
    wc = len(words)
    sentences = [s for s in _re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    shape = _admissions_shape(profile)
    is_uk = shape["is_uk"]

    cliches = _essay_find(lower, ESSAY_CLICHES)
    ai_tells = _essay_find(lower, AI_TELLS)
    vague = _essay_find(lower, VAGUE_WORDS)
    numbers = len(_re.findall(r"\b\d+\b", text))
    proper_nouns = len(_re.findall(r"(?<=[a-z,] )[A-Z][a-z]{2,}", text))
    sensory = len(_essay_find(lower, ["saw", "heard", "smelled", "felt", "touched", "watched", "noticed", "remember", "hands", "voice", "cold", "warm", "dark", "quiet", "loud"]))
    first_sentence = (sentences[0].strip() if sentences else "")

    dims = []
    def clamp(v):
        return max(0, min(5, v))
    def add_dim(name, score, note):
        dims.append({"name": name, "score": clamp(int(round(score))), "note": note})

    # 1. Hook
    hook = 3
    if _re.match(r"^(i am|i have always|i believe|throughout|my name is|the dictionary|webster)", first_sentence.lower()):
        hook -= 2
    if _re.match(r'^["\']', first_sentence):
        hook -= 1
    if _re.match(r"^(ever since|from a young|for as long)", first_sentence.lower()):
        hook -= 2
    if first_sentence and (_re.search(r"\b(when|the night|at \d|that morning|i was \d|the first time)\b", first_sentence.lower()) or (sensory > 0 and len(first_sentence) < 160)):
        hook += 1
    add_dim("Hook (opening)", hook, "Strong, specific opening that pulls the reader in." if hook >= 4 else "Serviceable opening - could start deeper inside a specific moment." if hook >= 3 else "Weak opening. Start inside a concrete scene, not a summary, thesis, or quote.")

    # 2. Specificity
    spec = 2 + min(2, (numbers + proper_nouns) // 3) + min(1, sensory // 3) - min(2, len(vague) // 2)
    add_dim("Specificity & detail", spec, "Rich, concrete detail - this is what makes an essay memorable." if spec >= 4 else "Some specifics; add more real names, numbers, and sensory detail." if spec >= 3 else "Too general. Swap vague words for exact, only-you details.")

    # 3. Voice
    voice = 5 - min(3, len(cliches)) - min(2, len(ai_tells))
    add_dim("Authentic voice", voice, "Sounds like a real person, not a template." if voice >= 4 else "Voice is okay but some phrasing is generic - see the flagged clichés." if voice >= 3 else "Reads generic/AI-like. The flagged phrases below appear in thousands of essays.")

    # 4. Reflection
    refl = 2
    if _re.search(r"\b(i realized|i learned|i understand now|changed how i|now i|taught me|i began to|made me see|i started to)\b", lower):
        refl += 2
    if _re.search(r"\b(because|which meant|so that|the reason)\b", lower):
        refl += 1
    if refl >= 4 and any(_re.search(r"taught me the true meaning|i realized that|i learned that", c["phrase"]) for c in cliches):
        refl -= 1  # reflection exists but clichéd
    add_dim("Reflection & insight", refl, "Genuine reflection on what the experience meant - the heart of a great essay." if refl >= 4 else "Some reflection; go deeper on how you actually changed." if refl >= 3 else "Missing real reflection. Show what shifted in how you think or act.")

    # 5. Structure
    struct = 3
    lens = [len(_re.findall(r"\b[\w']+\b", s)) for s in sentences]
    variety = (max(lens) - min(lens)) if len(lens) > 2 else 0
    avg_len = wc / len(sentences) if sentences else 0
    if variety >= 12:
        struct += 1
    elif variety <= 5 and len(lens) > 3:
        struct -= 1
    if avg_len > 30:
        struct -= 1
    if _re.search(r"\b(but|until|then|that changed|everything changed|one day)\b", lower):
        struct += 1
    add_dim("Structure & arc", struct, "Clear arc with good rhythm and a turning point." if struct >= 4 else "Structure holds; vary sentence length and sharpen the turn." if struct >= 3 else "Structure is flat. Build a clear before/after and vary your rhythm.")

    # 6. Prompt / format fit
    if is_uk:
        personal_open = bool(_re.match(r"^(i |ever since|from a young|for as long|when i was|growing up|my )", first_sentence.lower()))
        fit = 2 if personal_open else 4
        fit_note = "Good subject focus for a UK statement." if fit >= 4 else "For UK/UCAS this is too personal-narrative - lead with your subject, not your story (~80% academic)."
        add_dim("Subject/format fit", fit, fit_note)
    elif prompt:
        stop = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "your", "you", "with", "for", "how", "what", "why", "that", "this", "about", "describe", "tell", "us", "has", "have"}
        pw = [w for w in _re.findall(r"\b[a-z]{4,}\b", prompt.lower()) if w not in stop]
        hit = len([w for w in pw if w in lower])
        fit = round((hit / len(pw)) * 5) if pw else 3
        fit_note = "Directly engages the prompt." if fit >= 4 else "Partially addresses the prompt - make sure every part is answered." if fit >= 3 else "Drifts from the prompt. Re-read it and make sure you're answering what's asked."
        add_dim("Prompt fit", fit, fit_note)
    else:
        add_dim("Prompt fit", 3, "Paste the prompt for a prompt-alignment check. (US personal essays should still reveal who you are through a real story.)")

    weights = {"Hook (opening)": 1, "Specificity & detail": 1.4, "Authentic voice": 1.4, "Reflection & insight": 1.3, "Structure & arc": 1}
    wsum = 0.0
    w = 0.0
    for dd in dims:
        wt = weights.get(dd["name"], 1.1 if "fit" in dd["name"].lower() else 1)
        wsum += dd["score"] * wt
        w += wt
    overall10 = round((wsum / w) / 5 * 10, 1) if w else 0
    if overall10 >= 8:
        band = "Strong draft"
    elif overall10 >= 6.5:
        band = "Solid, with clear fixes"
    elif overall10 >= 4.5:
        band = "Needs real revision"
    else:
        band = "Early draft - rebuild the core"

    grounding = []
    ach = str(profile.get("student_achievements") or "").strip()
    if ach:
        ach_words = _re.findall(r"\b[a-z]{4,}\b", ach.lower())
        interest_words = _re.findall(r"\b[a-z]{4,}\b", str(profile.get("interests") or "").lower())
        pool = [w for w in set(ach_words + interest_words) if w not in ("with", "that", "this", "from", "have", "been", "your")]
        referenced = len([w for w in pool if w in lower])
        if pool and referenced == 0:
            grounding.append("Your essay doesn't seem to draw on anything from your actual logged profile (your achievements/interests). The strongest essays are rooted in what you've really done - consider whether this story connects to them.")
        elif referenced > 0:
            grounding.append("Good - this connects to your real logged profile. That authenticity is exactly what admissions readers can feel.")
    major = profile.get("intended_major")
    if major and is_uk and str(major).lower().split(" ")[0] not in lower:
        grounding.append(f"For a UK statement this must be about {major} - it currently doesn't mention your subject clearly.")

    school_note = None
    if shape["anchor"] and not is_uk and shape["anchor"].get("values"):
        school_note = f"{shape['anchor']['name']} particularly values {' and '.join(shape['anchor']['values'][:2])}. Where it's honest, make sure your story reflects qualities like that - shown, never name-dropped."

    return {
        "overall": overall10, "band": band, "word_count": wc, "sentence_count": len(sentences),
        "dimensions": dims,
        "cliches": [c["phrase"] for c in cliches], "ai_tells": [a["phrase"] for a in ai_tells], "vague": [v["phrase"] for v in vague],
        "grounding_notes": grounding, "school_note": school_note, "is_uk": is_uk,
    }
