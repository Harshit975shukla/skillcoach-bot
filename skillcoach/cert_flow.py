"""Certification prep in Telegram: choose a track, see domain readiness and practise exam-style sets."""

from skillcoach.certifications import DISCLAIMER, SESSION_SIZE, TRACKS, readiness
from skillcoach.models import Assessment, Questions
from skillcoach.timeutil import week_key


def domain_of(session):
    track_id, _, index = (session.source or "").partition(":")
    track = TRACKS.get(track_id)
    if not track or not index.isdecimal() or int(index) >= len(track.domains):
        return None, None
    return track, int(index)


class CertFlow:
    def __init__(self, service):
        self.s = service

    def command(self, arg):
        arg = arg.strip().lower()
        if arg in ("off", "stop"):
            self.leave()
        elif arg:
            self.choose(arg)
        elif self.s.state.cert_track in TRACKS:
            self.overview(TRACKS[self.s.state.cert_track])
        else:
            self.tracks()

    def tracks(self):
        self.s.say(
            "🎓 Certification prep. Choose an exam to aim for. You'll see its official domains, your "
            "readiness per domain from practice here, and original exam-style practice sets.\n\n"
            + DISCLAIMER,
            buttons=[
                [{"text": f"{t.name} · {t.code.split(' ')[0]}", "callback_data": f"cert:track:{t.id}"}]
                for t in TRACKS.values()
            ],
        )

    def choose(self, track_id):
        track = TRACKS.get(track_id)
        if track is None:
            self.s.say("Unknown track. Use /cert to choose one.")
            return
        self.s.state.cert_track = track.id
        self.overview(track, chosen=True)

    def leave(self):
        self.s.state.cert_track = None
        self.s.say("Certification goal cleared. Your practice history is kept. /cert to pick another.")

    def overview(self, track, *, chosen=False):
        view = readiness(self.s.state, track, self.s.now)
        lines = [
            f"🎓 {track.name} ({track.code})" + (" is now your certification goal." if chosen else ""),
            track.format,
        ]
        if track.hands_on:
            lines.append(
                "This exam is hands-on: practise the commands in your labs (/labs). These questions check reasoning."
            )
        lines.append("")
        for d in view["domains"]:
            weight = f" · {d['weight']}%" if d["weight"] else ""
            practice = (
                f"{d['practice_accuracy']}% of {d['practice_answers']} answers"
                if d["practice_answers"]
                else "no practice yet"
            )
            lines.append(
                f"• {d['name']}{weight}: {d['label']} ({practice}; "
                f"{d['topics_started']}/{d['topics_total']} related topics started)"
            )
        if view["overall"] is not None:
            lines.append(f"\nPractice accuracy across practised domains: {view['overall']}%")
        lines.append(f"\n{DISCLAIMER}\nOfficial exam guide: {track.source}")
        buttons = [
            [{"text": f"📝 Practise: {d['name'][:48]}", "callback_data": f"cert:p:{track.id}:{d['index']}"}]
            for d in view["domains"]
        ]
        buttons.append([{"text": "Change exam", "callback_data": "cert:list"}])
        self.s.say("\n".join(lines), buttons=buttons)

    def practice(self, track_id, index):
        from skillcoach.service import stable_id

        track = TRACKS.get(track_id)
        if track is None or not index.isdecimal() or int(index) >= len(track.domains):
            self.s.say("That practice button is no longer valid. Use /cert.")
            return
        if self.s.assessment_busy():
            return
        position = int(index)
        domain = track.domains[position]

        def exact(result):
            if len(result.questions) != SESSION_SIZE:
                raise ValueError(f"Exactly {SESSION_SIZE} questions required")
            if len({q.question for q in result.questions}) != SESSION_SIZE:
                raise ValueError("Questions must be distinct")

        result = self.s.structured(
            "cert-practice",
            f"Write EXACTLY {SESSION_SIZE} ORIGINAL exam-style multiple-choice questions to practise the "
            f"'{domain.name}' domain of the {track.name} ({track.code}) exam. Base them on the official exam "
            f"guide ({track.source}) and current official documentation. Use realistic scenarios at the exam's "
            "level, exactly one correct option among A-D, and explanations that say why the answer is right and "
            "why the most tempting wrong option is wrong. Never reproduce, paraphrase or claim to be real exam "
            "questions. Do not invent prices, quotas or limits. Set each topic to the domain name. "
            "Learner context:\n" + self.s.context(),
            Questions,
            exact,
        )
        ident = stable_id(self.s.job["id"] + ":cert")
        day = self.s.now.date()
        session = Assessment(
            id=ident,
            kind="cert",
            date=day,
            week=week_key(day),
            questions=result.questions,
            question_ids=[stable_id(f"{ident}:{i}") for i in range(SESSION_SIZE)],
            source=f"{track.id}:{position}",
        )
        self.s.expire_assessment()
        self.s.state.assessments[ident] = session
        self.s.state.active_assessment, self.s.state.focus = ident, "assessment"
        self.s.show_question(
            session,
            f"🎓 {track.name} practice · {domain.name}. Original exam-style questions; they never change your "
            "quiz scores, and missed ones return in /review.",
        )

    def completed(self, session, score):
        track, index = domain_of(session)
        if track is None:
            return f"🎓 Practice set complete: {score}/{len(session.questions)}.", None
        item = readiness(self.s.state, track, self.s.now)["domains"][index]
        text = (
            f"🎓 Practice set complete: {score}/{len(session.questions)}. {item['name']}: {item['label']} "
            f"({item['practice_accuracy']}% over {item['practice_answers']} practice answers). "
            "This reflects practice in SkillCoach only, not a predicted exam result."
        )
        buttons = [
            [{"text": "📝 Another set on this domain", "callback_data": f"cert:p:{track.id}:{index}"}],
            [{"text": "All domains", "callback_data": f"cert:track:{track.id}"}],
        ]
        return text, buttons
