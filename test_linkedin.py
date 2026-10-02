import pytest

from linkedin import is_login_wall, parse_feed, parse_post, post_key, profile_activity_url

FEED = """Sara Ali

Performance Marketing Lead | Ecommerce

Followers

1,200

Follow
Message
All activity
Posts
Feed post

Sara Ali

 • 2nd

Performance Marketing Lead | Ecommerce

1w

Connect

الـ ROAS اللي ظاهر في المنصة مش هو الحقيقي.
الطلبات الفعلية أقل من أرقام المنصة.
… more

Show translation

12 reactions
12

10 comments
10 comments

•

1 repost
1 repost

Like
Comment
Repost
Send
Feed post

Sara Ali reposted this

Omar Hassan

 • Following

Growth Marketer

2w • Edited

Connect

مبروك على الوظيفة الجديدة

Like
Comment
Repost
Send
Feed post

Sara Ali

 • 2nd

Performance Marketing Lead | Ecommerce

3d

Follow

Notes on attribution windows

1,024 reactions
Like
Comment
"""


def test_parses_author_headline_age_body_and_counts():
    first = parse_feed(FEED)[0]
    assert (first.author, first.headline, first.age) == ("Sara Ali", "Performance Marketing Lead | Ecommerce", "1w")
    assert first.text == "الـ ROAS اللي ظاهر في المنصة مش هو الحقيقي.\nالطلبات الفعلية أقل من أرقام المنصة."
    assert (first.reactions, first.comments, first.reposted_by) == (12, 10, None)


def test_reposts_keep_the_original_author_and_ignore_the_edited_marker():
    second = parse_feed(FEED)[1]
    assert (second.reposted_by, second.author, second.age) == ("Sara Ali", "Omar Hassan", "2w")
    assert second.text == "مبروك على الوظيفة الجديدة"


def test_follow_buttons_are_not_part_of_the_body_and_thousands_are_parsed():
    third = parse_feed(FEED)[2]
    assert (third.text, third.reactions) == ("Notes on attribution windows", 1024)


def test_three_posts_and_dedup_keys_are_stable():
    posts = parse_feed(FEED)
    assert len(posts) == 3
    assert len({post_key(p) for p in posts}) == 3


def test_text_without_posts_yields_nothing():
    assert parse_feed("Sign in to see more") == []


def test_single_post_text_falls_back_to_the_page_text():
    assert parse_post("  A short page with no feed markers.  ") == "A short page with no feed markers."
    assert parse_post(FEED).startswith("الـ ROAS")


@pytest.mark.parametrize("url", ["https://www.linkedin.com/login?x=1", "https://www.linkedin.com/authwall?trk=bf"])
def test_login_walls_are_detected(url):
    assert is_login_wall(url)


def test_normal_pages_are_not_login_walls():
    assert not is_login_wall("https://www.linkedin.com/in/sara-ali/recent-activity/all/")


@pytest.mark.parametrize("value", ["sara-ali", "https://www.linkedin.com/in/sara-ali/?trk=x", "/sara-ali/"])
def test_profile_urls_are_normalised(value):
    assert profile_activity_url(value) == "https://www.linkedin.com/in/sara-ali/recent-activity/all/"


def test_reacted_lines_end_the_body_and_count_reactions():
    text = "Feed post\n\nAmr\n\n • 2nd\n\nPM\n\n3d\n\n🤍\nSara Ali and 601 others reacted\nSara Ali and 601 others\n\n5 comments\nLike\nComment\n"
    post = parse_feed(text)[0]
    assert (post.text, post.reactions, post.comments) == ("🤍", 602, 5)


@pytest.mark.parametrize("value", ["sara ali", "sara/../admin", "https://evil.test/in/../x y", "", "--limit", "-sara"])
def test_unsafe_profile_values_are_rejected(value):
    with pytest.raises(ValueError):
        profile_activity_url(value)
