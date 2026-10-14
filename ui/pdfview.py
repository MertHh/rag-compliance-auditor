from streamlit_pdf_viewer import pdf_viewer


def show_pdf(data: bytes, annotations: list[dict], key: str) -> None:
    """Shows the PDF with boxes drawn over the cited text and scrolls to the first box."""
    pdf_viewer(
        data,
        width="100%",
        height=820,
        annotations=annotations,
        annotation_outline_size=2,
        scroll_to_annotation=1 if annotations else None,
        key=key,
    )
