_programs_text = """Accounting (Post-Baccalaureate) Certificate
Accounting Minor
Accounting, AS
Accounting, BS
Accounting, MS
Alcohol and Drug Counseling Graduate Certificate
Applied Behavior Analysis Minor
Art Minor
Biology Minor
Biology, BS
Business Administration, BS
Business Administration, MBA
Business Administration, MBA - 45 credit program
Business Intelligence and Analytics, MS
Certificate in Equine Veterinary Assistant
Certificate in Paralegal Studies
Chemistry Minor
Child Studies, BS
Clinical Mental Health Counseling, MS
Communication and Media Studies Minor
Communication and Media Studies, BA
Computer Information Systems, BS
Computer Science, MS
Corporate Innovation Graduate Certificate
Counseling and Human Services, MS
Criminal Justice Minor
Criminal Justice, AS
Criminal Justice, BS
Data Analytics Minor
Data Science, BS
Doctor of Business Administration (DBA)
Doctor of Nursing Practice (DNP)
Doctor of Nursing Practice - Educational Leadership Specialization
Doctor of Nursing Practice - Executive Leadership Specialization
Doctor of Nursing Practice - Informatics Leadership Specialization
Doctor of Nursing Practice - Professional Leadership Specialization
Early Childhood Education, AS
Education, M.Ed
Education, M.Ed. - 33 credit program
Emergency Management and Homeland Security Minor
Emergency Management and Homeland Security, BS
English Minor
Environmental Science Minor
Environmental Science, BS
Equine Studies Minor
Equine Studies, BS
Finance Graduate Certificate
Finance Minor
Finance, BS
Forensic Accounting Certificate
Forensic Psychology Minor
Gaming and Esports Management Minor
Gaming and Esports Management, BS
Gaming and Esports Management, MS
Higher Education Administration Graduate Certificate
Higher Education Leadership, MS
Human Resource Management Certificate
Human Resource Management, BS
Human Services Minor
Human Services, BS
Infection Prevention and Control Graduate Certificate
International Business Administration, BS
Leadership Graduate Certificate
Learning Design and Technology Graduate Certificate
Legal Studies Minor
Legal Studies, AS
Legal Studies, BS
Management and Leadership Minor
Management, AS
Management, BS
Marketing Graduate Certificate
Marketing Minor
Marketing, AS
Marketing, BS
Master of Business Administration Healthcare
Master of Science Nursing
Master of Science Nursing Adult Gerontology Primary Care Nurse Practitioner Specialization
Master of Science Nursing Case Management Specialization
Master of Science Nursing Family Nurse Practitioner Specialization
Master of Science Nursing Infection Prevention and Control Specialization
Master of Science Nursing Informatics Specialization
Master of Science Nursing Management and Organizational Leadership Specialization
Master of Science Nursing Nursing Education Specialization
Master of Science Nursing Psychiatric Mental Health Nurse Practitioner Specialization
Master of Science Nursing/Master of Business Administration Healthcare
Mathematics Minor
Nursing (RN to BSN), BSN
Ocean Conservation Minor
Online Teaching Graduate Certificate
Philosophy Minor
Pre-Athletic Trainer Track
Pre-Engineering Track
Pre-Health Track
Pre-Law Track
Professional Counseling Graduate Certificate
Project Management Graduate Certificate
Project Management, MS
Psychology Minor
Psychology, BA
Public Administration, MPA
Registered Nurse to Bachelor of Science Nursing
Registered Nurse to Bachelor of Science Nursing/Master of Science Nursing
Sociology Minor
Sociology, BA
Sport Management Minor
Sport Management, BS
Teaching English Language Learners Graduate Certificate"""


def _get_programs() -> list[str]:
    lines = _programs_text.splitlines()
    return list(dict.fromkeys([p.strip() for p in lines if p.strip()]))


PROGRAMS = _get_programs()
