from pathlib import Path

import pymupdf
import pytest

SAMPLE_CONTRACT = """MASTER SERVICES AGREEMENT

This Agreement is entered into between Acme Corp and Beta LLC.

1. Definitions
1.1 "Services" means the consulting services described in Exhibit A.
1.2 "Fees" means the amounts payable under Section 4.

2. Term and Termination
2.1 This Agreement commences on the Effective Date and continues for two years.
2.2 Either party may terminate this Agreement upon thirty (30) days written notice.

3. Limitation of Liability
3.1 The total aggregate liability of either party shall not exceed the fees paid in the twelve months preceding the claim.
3.2 Neither party shall be liable for indirect or consequential damages.

4. Governing Law
4.1 This Agreement is governed by the laws of the State of New York."""


@pytest.fixture
def sample_contract() -> str:
    return SAMPLE_CONTRACT


def _make_pdf(path, pages, password=None) -> Path:
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 72.0
        for text, size in lines:
            page.insert_text((72, y), text, fontsize=size)
            y += size * 1.6
    if password:
        doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256,
                 user_pw=password, owner_pw=password + "-owner")
    else:
        doc.save(str(path))
    doc.close()
    return Path(path)


@pytest.fixture
def make_pdf():
    return _make_pdf
