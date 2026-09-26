"""Real, downloadable .docx resume generation - the piece the
existing resume-building system was missing entirely. Every other
function in resume_builder.py polishes phrasing, checks ATS
alignment, or ranks entries, but the actual end product of "build me
a resume" is a real document a person can download and submit to an
employer. Until this, every polished bullet, every ATS check, every
tailored ranking stayed trapped as in-app text with nowhere real to
go.
 
Uses python-docx (not docx-js/Node) deliberately: this runs inside
the real, deployed FastAPI backend, which has Python available, not
Node. Structures the output as a real, professional resume - a
header with the person's real email (the only contact info the
current schema actually stores; never a fabricated name), an
optional summary, experience/education/projects grouped by type in
the conventional resume order, and a skills line. Every value comes
directly from the person's own real, already-polished data - if
something is missing (no summary generated yet, no skills claimed),
it's honestly left out rather than replaced with a placeholder like
"[Your Name]" that would make the document look broken or generic.
"""
 
from io import BytesIO
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
 
 
def _add_section_heading(doc, text):
    heading = doc.add_paragraph()
    heading.paragraph_format.space_before = Pt(14)
    heading.paragraph_format.space_after = Pt(4)
    run = heading.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(11)
    # A real, visible divider under the section label - a thin bottom
    # border on the paragraph, not a table (tables as horizontal
    # rules render inconsistently, per the docx skill's own guidance).
    p_pr = heading._p.get_or_add_pPr()
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    p_borders = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), '888888')
    p_borders.append(bottom)
    p_pr.append(p_borders)
    return heading
 
 
def generate_resume_document(email: str, summary_line: str | None, polished_entries: list[dict], skills: list[str]) -> bytes:
    """Builds a real .docx from a person's actual, already-polished
    resume data. Nothing here generates new content - every string
    placed into the document was already produced by a real person
    (their email) or an earlier, already-fabrication-checked step
    (summary_line from generate_resume_summary, polished_entries from
    polish_resume_entry, skills from build_skills_section's explicit
    list only - never suggested_additions, which are inferred, not
    claimed).
    """
    doc = Document()
 
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.6)
    section.bottom_margin = Inches(0.6)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)
 
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(10.5)
 
    header = doc.add_paragraph()
    header.alignment = WD_ALIGN_PARAGRAPH.CENTER
    header_run = header.add_run(email or "")
    header_run.font.size = Pt(13)
    header_run.bold = True
    header.paragraph_format.space_after = Pt(12)
 
    if summary_line and summary_line.strip():
        _add_section_heading(doc, "Summary")
        p = doc.add_paragraph(summary_line.strip())
        p.paragraph_format.space_after = Pt(4)
 
    # Group entries by type in the conventional resume order - work
    # experience first, then education, then projects - rather than
    # the order they happen to appear in polished_entries.
    by_type = {"work": [], "education": [], "project": []}
    for e in (polished_entries or []):
        t = (e.get("entry_type") or "work").lower()
        if t not in by_type:
            t = "work"
        by_type[t].append(e)
 
    section_labels = [("work", "Experience"), ("education", "Education"), ("project", "Projects")]
    for type_key, label in section_labels:
        entries = by_type[type_key]
        if not entries:
            continue
        _add_section_heading(doc, label)
        for e in entries:
            title = e.get("title") or ""
            org = e.get("org")
            dates = e.get("dates")
 
            title_para = doc.add_paragraph()
            title_para.paragraph_format.space_after = Pt(0)
            title_run = title_para.add_run(title)
            title_run.bold = True
            title_run.font.size = Pt(10.5)
            if dates:
                title_para.paragraph_format.tab_stops.add_tab_stop(Inches(7.0), alignment=3)  # right tab
                title_run2 = title_para.add_run(f"\t{dates}")
                title_run2.font.size = Pt(9.5)
                title_run2.italic = True
 
            if org:
                org_para = doc.add_paragraph()
                org_para.paragraph_format.space_after = Pt(2)
                org_run = org_para.add_run(org)
                org_run.italic = True
                org_run.font.size = Pt(10)
 
            bullets = e.get("bullets") or []
            for b in bullets:
                if not b or not str(b).strip():
                    continue
                bullet_para = doc.add_paragraph(style='List Bullet')
                bullet_para.paragraph_format.space_after = Pt(2)
                bullet_run = bullet_para.add_run(str(b).strip())
                bullet_run.font.size = Pt(10)
 
    if skills:
        _add_section_heading(doc, "Skills")
        p = doc.add_paragraph(", ".join(skills))
        p.paragraph_format.space_after = Pt(4)
 
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
 
