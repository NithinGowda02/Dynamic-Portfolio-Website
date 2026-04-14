from __future__ import annotations

from extensions import db


class Project(db.Model):
    __tablename__ = "projects"

    id            = db.Column(db.Integer, primary_key=True)
    title         = db.Column(db.Text, nullable=False)          # FIX 1: was nullable=True
    description   = db.Column(db.Text, nullable=False)          # FIX 1: was nullable=True
    tech_stack    = db.Column(db.Text, nullable=True)
    github_link   = db.Column(db.Text, nullable=True)
    project_image = db.Column(db.Text, nullable=True)           # nullable: cover image is optional
    live_demo     = db.Column(db.Text, nullable=True)

    # FIX 2: Use a proper order_by with column references instead of a raw
    # string. The string form silently does nothing if the column is renamed.
    images = db.relationship(
        "ProjectImage",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectImage.sort_order, ProjectImage.id",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} title={self.title!r}>"


class ProjectImage(db.Model):
    __tablename__ = "project_images"

    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,             # FIX 3: add index — project_id is queried heavily
    )
    image_file = db.Column(db.Text, nullable=False)
    # FIX 4: Add Python-side default=0 alongside server_default="0".
    # Without default=, SQLAlchemy doesn't populate the attribute after flush()
    # so any read before the next commit sees None instead of 0.
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    project = db.relationship("Project", back_populates="images")

    def __repr__(self) -> str:
        return f"<ProjectImage id={self.id} project_id={self.project_id}>"


class ProjectThumbnail(db.Model):
    __tablename__ = "project_thumbnails"

    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.Text, nullable=False)
    image_file = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")  # FIX 4

    def __repr__(self) -> str:
        return f"<ProjectThumbnail id={self.id} title={self.title!r}>"


class Skill(db.Model):
    __tablename__ = "skills"

    id         = db.Column(db.Integer, primary_key=True)
    skill_name = db.Column(db.Text, nullable=False)     # FIX 1: was nullable=True

    def __repr__(self) -> str:
        return f"<Skill id={self.id} skill_name={self.skill_name!r}>"


class Experience(db.Model):
    __tablename__ = "experience"

    id              = db.Column(db.Integer, primary_key=True)
    role            = db.Column(db.Text, nullable=False)    # FIX 1
    organization    = db.Column(db.Text, nullable=False)    # FIX 1
    duration        = db.Column(db.Text, nullable=False)    # FIX 1
    description     = db.Column(db.Text, nullable=False)    # FIX 1
    experience_file = db.Column(db.Text, nullable=True)     # optional PDF — stays nullable

    def __repr__(self) -> str:
        return f"<Experience id={self.id} role={self.role!r} org={self.organization!r}>"


class Certification(db.Model):
    __tablename__ = "certifications"

    id               = db.Column(db.Integer, primary_key=True)
    title            = db.Column(db.Text, nullable=False)   # FIX 1
    platform         = db.Column(db.Text, nullable=False)   # FIX 1
    year             = db.Column(db.Text, nullable=False)   # FIX 1
    certificate_file = db.Column(db.Text, nullable=True)    # optional — stays nullable

    def __repr__(self) -> str:
        return f"<Certification id={self.id} title={self.title!r}>"


class Profile(db.Model):
    __tablename__ = "profile"

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.Text, nullable=False)      # FIX 1
    title         = db.Column(db.Text, nullable=False)      # FIX 1
    about         = db.Column(db.Text, nullable=False)      # FIX 1
    email         = db.Column(db.Text, nullable=True)       # contact details optional
    github        = db.Column(db.Text, nullable=True)
    linkedin      = db.Column(db.Text, nullable=True)
    resume_file   = db.Column(db.Text, nullable=True)       # uploaded later
    profile_image = db.Column(db.Text, nullable=True)       # uploaded later

    def __repr__(self) -> str:
        return f"<Profile id={self.id} name={self.name!r}>"


class AboutContent(db.Model):
    __tablename__ = "about_content"

    id           = db.Column(db.Integer, primary_key=True)
    # FIX 5: Use server_default="" so the row inserted during AUTO_DB_CREATE
    # doesn't need explicit values, and nullable=False ensures no nulls later.
    preview_text = db.Column(db.Text, nullable=False, server_default="")
    details_text = db.Column(db.Text, nullable=False, server_default="")

    def __repr__(self) -> str:
        return f"<AboutContent id={self.id}>"


class AboutIntro(db.Model):
    __tablename__ = "about_intro"

    id          = db.Column(db.Integer, primary_key=True)
    headline    = db.Column(db.Text, nullable=False, server_default="")     # FIX 5
    role_line   = db.Column(db.Text, nullable=False, server_default="")     # FIX 5
    short_desc  = db.Column(db.Text, nullable=False, server_default="")     # FIX 5
    about_image = db.Column(db.Text, nullable=True)     # uploaded later — stays nullable

    def __repr__(self) -> str:
        return f"<AboutIntro id={self.id} headline={self.headline!r}>"


class AboutInterest(db.Model):
    __tablename__ = "about_interests"

    id          = db.Column(db.Integer, primary_key=True)
    label       = db.Column(db.Text, nullable=False)    # FIX 1
    count_value = db.Column(db.Integer, nullable=False, default=0, server_default="0")  # FIX 4
    sort_order  = db.Column(db.Integer, nullable=False, default=0, server_default="0")  # FIX 4

    def __repr__(self) -> str:
        return f"<AboutInterest id={self.id} label={self.label!r}>"


class Highlight(db.Model):
    __tablename__ = "highlights"

    id          = db.Column(db.Integer, primary_key=True)
    icon_key    = db.Column(db.Text, nullable=True)     # optional icon identifier
    title       = db.Column(db.Text, nullable=False)    # FIX 1
    description = db.Column(db.Text, nullable=False)    # FIX 1
    sort_order  = db.Column(db.Integer, nullable=False, default=0, server_default="0")  # FIX 4

    def __repr__(self) -> str:
        return f"<Highlight id={self.id} title={self.title!r}>"