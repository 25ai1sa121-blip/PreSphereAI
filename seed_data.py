import csv
from pathlib import Path

MCQ_HEAD = ["id", "subject", "topic", "difficulty", "year", "question",
            "option_a", "option_b", "option_c", "option_d", "answer", "explanation"]

MCQS = [
    ("Polity", "Executive", "Easy", 2018, "Who is the constitutional head of the Union executive of India?", "President", "Prime Minister", "Chief Justice", "Speaker", "A", "Article 53 vests the executive power of the Union in the President."),
    ("Polity", "Amendments", "Medium", 2019, "Fundamental Duties were added by which Constitutional Amendment?", "42nd", "44th", "73rd", "86th", "A", "The 42nd Amendment (1976) added Article 51A."),
    ("Polity", "Fundamental Rights", "Easy", 2020, "Right to Constitutional Remedies is guaranteed under which Article?", "Article 14", "Article 19", "Article 21", "Article 32", "D", "Article 32 allows citizens to approach the Supreme Court for enforcement of Fundamental Rights."),
    ("Polity", "Parliament", "Medium", 2017, "A Money Bill can be introduced only in the:", "Rajya Sabha", "Lok Sabha", "Either House", "Joint sitting", "B", "Money Bills originate only in the Lok Sabha."),
    ("Polity", "DPSP", "Medium", 2016, "Directive Principles of State Policy were borrowed from the Constitution of:", "USA", "UK", "Ireland", "Canada", "C", "DPSPs were inspired by the Irish Constitution."),
    ("Economy", "Monetary Policy", "Easy", 2018, "Repo rate is the rate at which the RBI lends to:", "Commercial banks", "Government", "NABARD", "Public", "A", "Repo rate is the short-term lending rate for commercial banks."),
    ("Economy", "Taxation", "Easy", 2019, "GST was implemented in India in:", "2015", "2016", "2017", "2018", "C", "GST came into effect on 1 July 2017."),
    ("Economy", "Fiscal Policy", "Medium", 2020, "Fiscal deficit equals total expenditure minus:", "Revenue receipts", "Total receipts excluding borrowings", "Tax revenue", "Capital receipts", "B", "Fiscal deficit = total expenditure - total receipts excluding borrowings."),
    ("Economy", "Planning", "Easy", 2017, "NITI Aayog replaced which body?", "Finance Commission", "Planning Commission", "RBI", "SEBI", "B", "NITI Aayog replaced the Planning Commission in 2015."),
    ("Economy", "Agriculture", "Medium", 2021, "Minimum Support Prices are announced on the recommendation of:", "NABARD", "CACP", "SEBI", "FCI", "B", "CACP recommends MSP for notified crops."),
    ("Geography", "Rivers", "Easy", 2018, "Which is the longest river of peninsular India?", "Krishna", "Godavari", "Kaveri", "Narmada", "B", "The Godavari is the longest peninsular river."),
    ("Geography", "Mountains", "Medium", 2019, "The highest peak of the Western Ghats is:", "Doddabetta", "Anamudi", "Mahendragiri", "Kalsubai", "B", "Anamudi (2,695 m) in Kerala is the highest."),
    ("Geography", "Climate", "Medium", 2020, "Through how many Indian states does the Tropic of Cancer pass?", "6", "7", "8", "9", "C", "It passes through eight states."),
    ("Geography", "Lakes", "Easy", 2017, "Chilika lake is located in:", "Andhra Pradesh", "Odisha", "Tamil Nadu", "West Bengal", "B", "Chilika is a brackish lagoon in Odisha."),
    ("Geography", "Soils", "Easy", 2016, "Black soil is most suitable for:", "Cotton", "Tea", "Rubber", "Jute", "A", "Regur (black) soil retains moisture and suits cotton."),
    ("History", "Ancient India", "Easy", 2018, "Who founded the Mauryan Empire?", "Ashoka", "Chandragupta Maurya", "Bindusara", "Harshavardhana", "B", "Chandragupta Maurya founded it c. 321 BCE."),
    ("History", "Modern India", "Easy", 2019, "The Revolt of 1857 began at:", "Delhi", "Kanpur", "Meerut", "Lucknow", "C", "It began at Meerut on 10 May 1857."),
    ("History", "Freedom Movement", "Medium", 2020, "The Quit India Movement was launched in:", "1930", "1940", "1942", "1946", "C", "Launched in August 1942 at Gowalia Tank, Bombay."),
    ("History", "Ancient India", "Medium", 2017, "Who wrote the Arthashastra?", "Kalidasa", "Kautilya", "Banabhatta", "Vishakhadatta", "B", "Kautilya (Chanakya) is the traditional author."),
    ("History", "Modern India", "Medium", 2021, "The Battle of Plassey was fought in:", "1757", "1764", "1761", "1799", "A", "Plassey (1757) established Company dominance in Bengal."),
    ("Environment", "biodiversity","Easy",2018,"which of the foolowing is biodiversity hotspot?","Himalaya","Indo Burma","Sundalands","All of the above","D","All of the above are biodiversity hotspots."),


    ("Environment", "Conventions", "Easy", 2018, "The Ramsar Convention is related to the conservation of:", "Wetlands", "Ozone layer", "Deserts", "Whales", "A", "Ramsar is an international treaty for wetland conservation."),

    ("Environment", "Conventions", "Medium", 2019, "The Montreal Protocol deals with:", "Greenhouse gases", "Ozone-depleting substances", "Biodiversity", "Hazardous waste", "B", "It phases out substances that deplete the ozone layer."),

    ("Environment", "Wildlife", "Easy", 2017, "Project Tiger was launched in:", "1973", "1980", "1991", "2002", "A", "Project Tiger started in 1973 to protect tigers and their habitat."),

    ("Environment", "Biodiversity", "Medium", 2020, "Which of these is a biodiversity hotspot in India?", "Western Ghats", "Thar Desert", "Deccan Plateau", "Gangetic Plain", "A", "The Western Ghats is one of the global biodiversity hotspots."),

    ("Environment", "Institutions", "Medium", 2021, "The National Green Tribunal was established in:", "2005", "2008", "2010", "2014", "C", "The NGT was set up under the NGT Act 2010."),

]

MAINS_HEAD = ["id", "paper", "subject", "question", "marks", "word_limit", "keywords", "model_answer"]
MAINS = [
    ("M1", "GS-II", "Polity", "Discuss the role of the Governor in Centre-State relations. Is the office still relevant?", 10, 150,
     "Article 155;Article 163;Sarkaria Commission;Punchhi Commission;discretionary powers;federalism",
     "The Governor is the constitutional head of a state under Article 155 and acts on aid and advice under Article 163 except in discretionary matters. Sarkaria and Punchhi Commissions recommended safeguards against misuse. The office remains relevant for federal balance but needs neutrality. Way forward: fixed tenure and consultation with the state."),
    ("M2", "GS-III", "Economy", "Examine the impact of GST on India's federal fiscal structure.", 10, 150,
     "GST Council;cooperative federalism;compensation cess;indirect taxes;101st Amendment",
     "GST, introduced by the 101st Amendment, subsumed many indirect taxes. The GST Council embodies cooperative federalism but states lost fiscal autonomy and depend on compensation. Way forward: simplify slabs and ensure fair revenue sharing."),
    ("M3", "GS-I", "Geography", "Explain the causes and consequences of urban flooding in Indian cities.", 10, 150,
     "urbanisation;drainage;encroachment;Mumbai floods 2005;NDMA;climate change",
     "Unplanned urbanisation, encroachment of wetlands, poor drainage and extreme rainfall cause urban floods as in Mumbai 2005. Consequences include loss of life, disease and economic damage. NDMA guidelines, stormwater planning and wetland protection are the way forward."),
    ("M4", "GS-I", "History", "Assess the contribution of the Moderates in the Indian national movement.", 10, 150,
     "Dadabhai Naoroji;Gokhale;drain theory;constitutional methods;Surat split",
     "Moderates like Naoroji and Gokhale used petitions and constitutional methods, exposed colonial exploitation through the drain theory and built political awareness. Their limits led to the Surat split, but they laid the foundation of nationalism."),
    ("M5", "GS-II", "Polity", "Civil services reforms must go beyond recruitment and institutional training to cope with today's challenges. Analyse.", 15, 250,
     "Mission Karmayogi;Second ARC;lateral entry;capacity building;performance appraisal;e-governance",
     "Reforms must extend to continuous capacity building through Mission Karmayogi, performance appraisal, lateral entry and e-governance as the Second ARC recommended. Way forward: accountability, domain expertise and ethical conduct."),
]

INTERVIEW = [
    ("I001", "Introduction", "Tell me about yourself and why you want to join the civil services."),
    ("I002", "Administration", "How would you handle political pressure as a District Magistrate?"),
    ("I003", "Administration", "How would you tackle corruption in your district?"),
    ("I004", "Administration", "How would you balance development and environmental protection?"),
    ("I005", "International Relations", "What is India's position in the Russia Ukraine conflict?"),    
    ("I006", "International Relations", "How should India manage its relationship with China?"),    
    ("I007", "Ethics", "Is it ever right to break a rule for a greater good?"),
    ("I008", "Ethics", "Should a state be allowed to secede from India if the majority of its population supports it?"),
    ("I009", "Science and technology", "What is the future of electric vehicles in India can Indian EV companies compete with Tesla?."),
    ("I0010", "Science and Technology", "Why is Aadhaar biometric information updated for children after they turn five?."),
    ("I0011", "Economy", "What is a double-engine government? What are its advantages and disadvantages?."),
    ("I0012", "Environment", "Why should India reduce its dependence on fossil fuels?"),
    ("I0013", "Technology", "How can AI contribute to governance and public service?."),
    ("I0030", "Current Affairs", "What is your opinion on the use of AI in governance?"),
    ("I002", "Introduction", "Why Civil Services instead of a private-sector job?."),
    ("I0040", "Social Issues", "How can technology improve rural education in India?"),

]

KNOWLEDGE = [
    ("Fundamental Rights", "Fundamental Rights (Part III, Articles 12-35) include equality, freedom, protection against exploitation, freedom of religion, cultural and educational rights and constitutional remedies. They are justiciable and enforceable through Articles 32 and 226."),
    ("GDP vs GNP", "GDP measures the value of goods and services produced within a country's borders. GNP = GDP + net factor income from abroad, so it counts output by a country's residents anywhere."),
    ("Federalism", "India is quasi-federal: a strong Centre, division of powers via the Seventh Schedule, and an independent judiciary as arbiter."),
    ("Monsoon", "The Indian monsoon is driven by differential heating of land and sea, the shift of the ITCZ and the Tibetan plateau heating; the south-west monsoon brings about 75% of annual rainfall."),
]


def _write(path, head, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


def ensure(data: Path):
    data.mkdir(exist_ok=True)
    if not (data / "mcqs.csv").exists() and not (data / "upsc_mcqs.csv").exists():
        _write(data / "mcqs.csv", MCQ_HEAD, [(f"Q{i + 1}",) + r for i, r in enumerate(MCQS)])
    if not (data / "mains_questions.csv").exists() and not (data / "upsc_mains_questions.csv").exists():
        _write(data / "mains_questions.csv", MAINS_HEAD, MAINS)
    if not (data / "interview_questions.csv").exists():
        _write(data / "interview_questions.csv", ["id", "category", "question"], INTERVIEW)
    if not (data / "doubt_knowledge.csv").exists():
        _write(data / "doubt_knowledge.csv", ["topic", "content"], KNOWLEDGE)