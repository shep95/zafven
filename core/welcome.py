"""The server owner's invitation copy, preserved verbatim."""
import config

DEFAULT_INVITATION = """hey guys, aureon has updated the houseofasher server and reinvites all of you guys back into the house. some of you guys have been amazing and loyal, we love that.

we plan on expanding houseofasher soon and would love all of you guys to be part of it. asher is silently working in the background with some people whom society calls important but asher doesn't think there important, houseofasher will be conquering soon so would love to expand the family of houseofasher.

now ofc we been working on some softwares which many of you guys have seen in action or heard about and these softwares are there to protect houseofasher and the prince. see you guys soon!

i know asher (aureon) gets talked alot about in different servers, communities, and on other social media platforms. please know that there are a lot of haters who can't think like he can so please have some patience's with him. he may not seem like anything on the surface but he does get called unique and he. he  is well known amongst the hierarchy circle of the global world for being young. for he can say a lot of things out of pride and ego and he has been working on it, i promise, but again please be patience with him. and i know he says a lot of stuff about what he going to do in the future but known he does that for a reason because for some reason he believes (which turns true 99%) of the time of which he would accomplish something in this world and everyone kinda disagrees and then he does which annoys a lot of people.

~ zafven

{invite_link}"""


def render_invitation(link: str, text: str | None = None) -> str:
    template = text if text is not None else config.WELCOME_DM_MESSAGE or DEFAULT_INVITATION
    if "{invite_link}" in template:
        return template.replace("{invite_link}", link)
    return template + "\n\n" + link
