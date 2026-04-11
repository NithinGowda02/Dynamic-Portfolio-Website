from __future__ import annotations

from extensions import db


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    tech_stack = db.Column(db.Text, nullable=True)
    github_link = db.Column(db.Text, nullable=True)
    project_image = db.Column(db.Text, nullable=True)
    live_demo = db.Column(db.Text, nullable=True)

    images = db.relationship(
        "ProjectImage",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="(ProjectImage.sort_order.asc(), ProjectImage.id.asc())",
    )


class ProjectImage(db.Model):
    __tablename__ = "project_images"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    image_file = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, server_default="0")

    project = db.relationship("Project", back_populates="images")


class ProjectThumbnail(db.Model):
    __tablename__ = "project_thumbnails"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=False)
    image_file = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, server_default="0")


class Skill(db.Model):
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    skill_name = db.Column(db.Text, nullable=True)


class Experience(db.Model):
    __tablename__ = "experience"

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.Text, nullable=True)
    organization = db.Column(db.Text, nullable=True)
    duration = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    experience_file = db.Column(db.Text, nullable=True)


class Certification(db.Model):
    __tablename__ = "certifications"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=True)
    platform = db.Column(db.Text, nullable=True)
    year = db.Column(db.Text, nullable=True)
    certificate_file = db.Column(db.Text, nullable=True)


class Profile(db.Model):
    __tablename__ = "profile"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=True)
    title = db.Column(db.Text, nullable=True)
    about = db.Column(db.Text, nullable=True)
    email = db.Column(db.Text, nullable=True)
    github = db.Column(db.Text, nullable=True)
    linkedin = db.Column(db.Text, nullable=True)
    resume_file = db.Column(db.Text, nullable=True)
    profile_image = db.Column(db.Text, nullable=True)


class AboutContent(db.Model):
    __tablename__ = "about_content"

    id = db.Column(db.Integer, primary_key=True)
    preview_text = db.Column(db.Text, nullable=True)
    details_text = db.Column(db.Text, nullable=True)


class AboutIntro(db.Model):
    __tablename__ = "about_intro"

    id = db.Column(db.Integer, primary_key=True)
    headline = db.Column(db.Text, nullable=True)
    role_line = db.Column(db.Text, nullable=True)
    short_desc = db.Column(db.Text, nullable=True)
    about_image = db.Column(db.Text, nullable=True)


class AboutInterest(db.Model):
    __tablename__ = "about_interests"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.Text, nullable=True)
    count_value = db.Column(db.Integer, nullable=False, server_default="0")
    sort_order = db.Column(db.Integer, nullable=False, server_default="0")


class Highlight(db.Model):
    __tablename__ = "highlights"

    id = db.Column(db.Integer, primary_key=True)
    icon_key = db.Column(db.Text, nullable=True)
    title = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, server_default="0")

