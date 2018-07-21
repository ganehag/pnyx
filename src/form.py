from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, TextAreaField, SubmitField,
                     HiddenField)
from wtforms import SelectField, SelectMultipleField, validators

from flask_wtf.recaptcha import RecaptchaField

from urllib.parse import urlparse, urljoin
from flask import request, url_for, redirect


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
        ref_url.netloc == test_url.netloc


def get_redirect_target():
    for target in request.args.get('next'), None:  # , request.referrer
        if not target:
            continue
        if is_safe_url(target):
            return target


class Select2MultipleField(SelectMultipleField):
    def pre_validate(self, form):
        # Prevent "not a valid choice" error
        pass

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = ",".join(valuelist)
        else:
            self.data = ""


class RedirectForm(FlaskForm):
    next = HiddenField()

    def __init__(self, *args, **kwargs):
        FlaskForm.__init__(self, *args, **kwargs)
        if not self.next.data:
            self.next.data = get_redirect_target() or ''

    def redirect(self, endpoint='index', **values):
        if is_safe_url(self.next.data):
            return redirect(self.next.data)
        target = get_redirect_target()
        return redirect(target or url_for(endpoint, **values))


class LoginForm(RedirectForm):
    username = StringField('username')
    password = PasswordField('password')
    submit = SubmitField('submit')


class RegisterForm(RedirectForm):
    email = StringField('email')
    username = StringField('username')
    password = PasswordField('password')
    submit = SubmitField('submit')
    recaptcha = RecaptchaField()


class CommunityCreateForm(RedirectForm):
    name = StringField('name', [
        validators.DataRequired(),
        validators.Length(min=3, max=50)])
    description = TextAreaField('description', [
        validators.DataRequired()])
    tags = Select2MultipleField(
        "tags", [], choices=[], render_kw={"multiple": "multiple"})
    recaptcha = RecaptchaField()
