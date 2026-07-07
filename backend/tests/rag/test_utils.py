from bs4 import BeautifulSoup

from app.rag.utils import html_for_markdown, html_to_markdown, normalize_pdf_extracted_text


def _markdown_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return html_to_markdown(html_for_markdown(soup))


def test_html_for_markdown_keeps_inline_links_in_sentences() -> None:
    markdown = _markdown_from_html(
        '<p>Read the <a href="https://demo-university.example.edu/catalog">Catalog</a> '
        "before applying.</p>"
    )

    assert (
        "Read the [Catalog](https://demo-university.example.edu/catalog) before applying."
        in markdown
    )
    assert (
        "Read the\n[Catalog](https://demo-university.example.edu/catalog)\nbefore applying."
        not in markdown
    )


def test_html_for_markdown_preserves_whitespace_only_inline_separators() -> None:
    markdown = _markdown_from_html(
        "<p>Available in person, including<em>&nbsp;</em>offices and classrooms.</p>"
        "<p><strong>Hybrid</strong><em>&nbsp;</em><strong>offices</strong> are open.</p>"
    )

    assert "including offices and classrooms" in markdown
    assert "includingoffices" not in markdown
    assert "**Hybrid offices** are open." in markdown
    assert "**Hybrid****offices**" not in markdown


def test_html_for_markdown_coalesces_adjacent_formatting_tags() -> None:
    markdown = _markdown_from_html(
        "<p><strong>Program Chair</strong><strong>, Health Sciences</strong></p>"
        "<p><strong>H</strong><strong>a</strong><strong>r</strong><strong>assment</strong></p>"
        "<p><strong>On campus)</strong><strong>to join our team.</strong></p>"
        "<p><strong>A</strong> <strong>B</strong></p>"
        "<p><strong>Chair</strong> <strong>, Health Sciences</strong></p>"
    )

    assert "**Program Chair, Health Sciences**" in markdown
    assert "**Program Chair****, Health Sciences**" not in markdown
    assert "**Harassment**" in markdown
    assert "Har assment" not in markdown
    assert "**On campus) to join our team.**" in markdown
    assert "On campus)to" not in markdown
    assert "**A B**" in markdown
    assert "**AB**" not in markdown
    assert "**Chair, Health Sciences**" in markdown
    assert "Chair ," not in markdown


def test_html_for_markdown_preserves_compact_tag_boundary_spacing() -> None:
    markdown = _markdown_from_html(
        "<p><strong>Contact info:<br /></strong>Phone: 203.932.2939</p>"
        '<p><img src="https://demo-university.example.edu/badge.png" alt="Badge" />'
        "Demo University</p>"
        '<p><strong><a href="https://demo-university.example.edu/guide.pdf">Guide</a>'
        "</strong>(PDF)</p>"
        "<p>H<sub>2</sub>O and Demo<sup>®</sup> University</p>"
    )

    assert "**Contact info:** Phone: 203.932.2939" in markdown
    assert "**Contact info:**Phone" not in markdown
    assert "![Badge](https://demo-university.example.edu/badge.png) Demo University" in markdown
    assert ")Demo University" not in markdown
    assert "**[Guide](https://demo-university.example.edu/guide.pdf)** (PDF)" in markdown
    assert "**[Guide](https://demo-university.example.edu/guide.pdf)**(PDF)" not in markdown
    assert "H2O and Demo® University" in markdown
    assert "H2 O" not in markdown


def test_normalize_pdf_extracted_text_collapses_character_per_line_runs() -> None:
    text = (
        "## Page 1\n\n"
        "A\nl\nl\n \no\nf\n \nt\nh\ne\n \nc\nl\na\ns\ns\nr\no\no\nm\ns\n"
        " \nh\na\nv\ne\n \nc\nh\na\nn\ng\ne\nd\n.\nA\nl\nl\n"
        " \nf\nr\nu\ns\nt\nr\na\nt\ni\nn\ng\n \n.\n \nW\ni\nt\nh\n \nh\ne\nl\np\n.\n"
        "U\n.\nS\n.\n \nD\ne\np\na\nr\nt\nm\ne\nn\nt\n.\n"
        "G E T T I N G  S T A R T E D\n"
        "E\nv\ne\nr\ny\n \nc\nl\na\ns\ns\nr\no\no\nm\n.\n"
    )

    normalized = normalize_pdf_extracted_text(text)

    assert "All of the classrooms have changed." in normalized
    assert "frustrating. With" in normalized
    assert "changed. All" in normalized
    assert "U.S. Department." in normalized
    assert "U. S. Department" not in normalized
    assert "GETTING STARTED" in normalized
    assert "Every classroom.\n" in normalized
    assert not normalized.endswith("\n\n")
    assert "A\nl\nl" not in normalized
    assert "E\nv\ne\nr\ny" not in normalized


def test_normalize_pdf_extracted_text_collapses_letter_spaced_lines() -> None:
    text = (
        "G e n e r a l   R e m i n d e r s :\n"
        "N 5 1 2 : A d v a n c e d   P a t h o p h y s i o l o g y\n"
        "3 P   E x a m"
    )

    normalized = normalize_pdf_extracted_text(text)

    assert "General Reminders:" in normalized
    assert "N512: Advanced Pathophysiology" in normalized
    assert "3P Exam" in normalized


def test_normalize_pdf_extracted_text_drops_blank_separated_vertical_labels() -> None:
    text = "M\n\nO\n\nD\n\nA\n\nL\n\nI\n\nT\n\nY\n\nNext section"

    normalized = normalize_pdf_extracted_text(text)

    assert "MODALITY" not in normalized
    assert "M\n\nO" not in normalized
    assert "Next section" in normalized


def test_normalize_pdf_extracted_text_keeps_short_numbered_fragments() -> None:
    text = "1\n\n2\n\n3\n\n4\n\nOn the Campus Page"

    normalized = normalize_pdf_extracted_text(text)

    assert normalized == text
