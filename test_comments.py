from comments import comments_section

PAGE = """Feed post

Sara Example

 • 2nd

1w

مشكلة في meta pixel

3 comments
3 comments

Like
Comment
Repost
Send

Most relevant

Omar Example  2nd

1w

check console errors

About

Accessibility
"""


def test_returns_only_the_comments_between_the_sort_label_and_the_footer():
    section = comments_section(PAGE)

    assert "check console errors" in section
    assert "مشكلة في meta pixel" not in section
    assert "Accessibility" not in section


def test_returns_empty_when_the_post_has_no_comment_section():
    assert comments_section("Feed post\n\nSomeone\n\n1w") == ""


def test_accepts_the_most_recent_sort_label():
    assert comments_section("Most recent\n\nhello\n\nAbout") == "hello"
