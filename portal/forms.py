import re
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _
from .models import User, Application, ApplicationDocument, Citizen, UserProfile, Department, Scheme, EligibilityRule, CompensationConfiguration, CertificateTemplate, GovernmentService, ServiceDocumentRequirement, EmailTemplate, MODULES

# Indian mobile numbers: 10 digits beginning with 6, 7, 8 or 9.
MOBILE_PATTERN = re.compile(r'^[6-9]\d{9}$')

def clean_indian_mobile(value, required=False):
    """Normalise (+91 / 0 prefixes, spaces, dashes) and validate a mobile number."""
    digits = re.sub(r'\D', '', value or '')
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    if not digits:
        if required:
            raise forms.ValidationError(_('Enter your 10-digit mobile number.'))
        return ''
    if not MOBILE_PATTERN.match(digits):
        raise forms.ValidationError(_('Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.'))
    return digits

class RegisterForm(UserCreationForm):
    name = forms.CharField(
        label=_('Full name'), max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Aman Shaikh', 'autocomplete': 'name'}))
    email = forms.EmailField(
        label=_('Email address'), required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'aman.shaikh@example.com', 'autocomplete': 'email'}))
    class Meta:
        model = User
        fields = ('name', 'email', 'mobile', 'password1', 'password2')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        mobile = self.fields['mobile']
        mobile.required = True
        mobile.label = _('Mobile number')
        mobile.help_text = _('10 digits, starting with 6, 7, 8 or 9.')
        mobile.widget = forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': '98765 43210', 'inputmode': 'numeric',
            'autocomplete': 'tel', 'maxlength': '17', 'pattern': r'[0-9+\-\s]{10,17}',
        })
        for field in ('password1', 'password2'):
            self.fields[field].widget.attrs['class'] = 'form-control'
        self.fields['password1'].widget.attrs['autocomplete'] = 'new-password'
        self.fields['password2'].widget.attrs['autocomplete'] = 'new-password'
    def clean_mobile(self):
        return clean_indian_mobile(self.cleaned_data.get('mobile'), required=True)
    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account already uses that email address.')
        return email
    @staticmethod
    def _unique_username(email):
        base = (email.split('@')[0] or 'citizen')[:140] or 'citizen'
        username, suffix = base, 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f'{base}{suffix}'
        return username
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        # Citizens sign in with their email, so the login handle is derived from it.
        user.username = self._unique_username(user.email)
        parts = (self.cleaned_data.get('name') or '').strip().split(None, 1)
        user.first_name = (parts[0] if parts else '')[:150]
        user.last_name = (parts[1] if len(parts) > 1 else '')[:150]
        user.role = User.Role.CITIZEN
        if commit:
            user.save()
            Citizen.objects.get_or_create(user=user)
            UserProfile.objects.get_or_create(user=user)
        return user

class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ('category', 'scheme', 'description', 'income', 'land_area')
        widgets = {'description': forms.Textarea(attrs={'rows': 4}), 'income': forms.NumberInput(attrs={'min': '0'}), 'land_area': forms.NumberInput(attrs={'min': '0', 'step': '0.001'})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['scheme'].queryset = Scheme.objects.filter(active=True)
        self.fields['scheme'].required = False
        for name in self.fields:
            css = 'form-select' if name in ('category', 'scheme') else 'form-control'
            self.fields[name].widget.attrs.setdefault('class', css)
    def clean(self):
        data = super().clean()
        if data.get('category') == Application.Category.LAND and not data.get('land_area'):
            self.add_error('land_area', 'Enter the land area for a land acquisition application.')
        if data.get('category') == Application.Category.WELFARE and not data.get('scheme'):
            self.add_error('scheme', 'Select the welfare scheme you are applying for.')
        return data

class DocumentForm(forms.ModelForm):
    class Meta:
        model = ApplicationDocument
        fields = ('file',)
    def clean_file(self):
        f = self.cleaned_data['file']
        if f.size > 8 * 1024 * 1024: raise forms.ValidationError('Maximum upload size is 8 MB.')
        import os
        if os.path.splitext(f.name)[1].lower() not in {'.pdf','.jpg','.jpeg','.png'}: raise forms.ValidationError('Upload PDF, JPG, JPEG or PNG only.')
        return f

class ProfileForm(forms.ModelForm):
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'mobile', 'address', 'district', 'taluka', 'village')
        widgets = {name: forms.TextInput(attrs={'class': 'form-control'}) for name in ('first_name', 'last_name', 'email', 'mobile', 'district', 'taluka', 'village')}
        widgets['address'] = forms.Textarea(attrs={'class': 'form-control', 'rows': 3})
        widgets['email'] = forms.EmailInput(attrs={'class': 'form-control'})
    def clean_mobile(self):
        return clean_indian_mobile(self.cleaned_data.get('mobile'))

class DepartmentForm(forms.ModelForm):
    categories = forms.MultipleChoiceField(
        choices=Application.Category.choices, required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
        label='Application categories handled',
        help_text='New cases of these categories are routed to this department automatically.')
    class Meta:
        model = Department
        fields = ('name', 'code', 'categories', 'description', 'active')
        widgets = {'name': forms.TextInput(attrs={'class': 'form-control'}), 'code': forms.TextInput(attrs={'class': 'form-control'}), 'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2})}

class SchemeForm(forms.ModelForm):
    class Meta:
        model = Scheme
        fields = ('name', 'category', 'income_limit', 'description', 'required_documents', 'active')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(choices=Application.Category.choices, attrs={'class': 'form-select'}),
            'income_limit': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'required_documents': forms.TextInput(attrs={'class': 'form-control'}),
        }

class EligibilityRuleForm(forms.ModelForm):
    class Meta:
        model = EligibilityRule
        fields = ('scheme', 'name', 'field_name', 'operator', 'threshold', 'active')
        widgets = {name: forms.TextInput(attrs={'class': 'form-control'}) for name in ('name', 'field_name', 'threshold')}
        widgets['scheme'] = forms.Select(attrs={'class': 'form-select'})
        widgets['operator'] = forms.Select(attrs={'class': 'form-select'})
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['scheme'].queryset = Scheme.objects.filter(active=True)
        self.fields['field_name'].help_text = 'Use income, land_area, documents, or form.field_name.'

class CompensationConfigForm(forms.ModelForm):
    class Meta:
        model = CompensationConfiguration
        fields = ('land_category', 'base_rate', 'multiplier', 'additional_components', 'deductions', 'active')
        widgets = {'land_category': forms.TextInput(attrs={'class': 'form-control'})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('base_rate', 'multiplier', 'additional_components', 'deductions'):
            self.fields[name].widget.attrs.update({'class': 'form-control', 'step': '0.001'})

class StaffAccountForm(forms.Form):
    username = forms.CharField(
        max_length=150, required=False,
        label='Officer ID (optional)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Auto-generated from the name if left empty', 'autocomplete': 'off'}))
    first_name = forms.CharField(
        max_length=150, label='First name',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Ravi', 'autocomplete': 'off'}))
    last_name = forms.CharField(
        max_length=150, required=False, label='Last name (optional)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Naik', 'autocomplete': 'off'}))
    email = forms.EmailField(
        label='Official email', help_text='The activation email and temporary password are sent to this address.',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'off', 'placeholder': "officer@gov.in"}))
    password = forms.CharField(
        min_length=8, required=False,
        label='Temporary password (optional)',
        help_text='Leave blank to auto-generate a secure temporary password.',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password', 'placeholder': 'Auto-generated if left empty'}))
    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(active=True), required=False, label='Department',
        empty_label='— Assign later —', widget=forms.Select(attrs={'class': 'form-select'}))
    designation = forms.CharField(
        max_length=120, required=False, label='Designation',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Deputy Collector'}))
    allowed_modules = forms.MultipleChoiceField(
        choices=MODULES, required=False, label='Allowed modules',
        widget=forms.CheckboxSelectMultiple(),
        help_text='Leave empty to allow every module.')
    allowed_categories = forms.MultipleChoiceField(
        choices=Application.Category.choices, required=False, label='Allowed application categories',
        widget=forms.CheckboxSelectMultiple(),
        help_text='Leave empty to allow every category.')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.errors:
            widget = self.fields[name].widget
            css = widget.attrs.get('class', '')
            if 'is-invalid' not in css:
                widget.attrs['class'] = f'{css} is-invalid'.strip()
    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if username and User.objects.filter(username=username).exists():
            raise forms.ValidationError('That username is already in use.')
        return username
    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account already uses that email address.')
        return email

class DirectMessageForm(forms.Form):
    """Lets the Collector email a specific officer or citizen from inside the app."""
    recipient = forms.ChoiceField(label='Recipient', widget=forms.Select(attrs={'class': 'form-select'}))
    subject = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Subject of the email'}))
    message = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 6, 'placeholder': 'Write your message to the officer or citizen...'}))
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        groups = []
        officers = User.objects.filter(role=User.Role.OFFICER, is_active=True).exclude(email='').order_by('username')
        citizens = User.objects.filter(role=User.Role.CITIZEN, is_active=True).exclude(email='').order_by('username')
        if officers:
            groups.append(('Officers', [(str(user.pk), f'{user.get_full_name() or user.username} — {user.email}') for user in officers]))
        if citizens:
            groups.append(('Citizens', [(str(user.pk), f'{user.get_full_name() or user.username} — {user.email}') for user in citizens]))
        self.fields['recipient'].choices = groups or [('', 'No officer or citizen has an email address yet')]
    def clean_recipient(self):
        value = (self.cleaned_data.get('recipient') or '').strip()
        user = User.objects.filter(pk=value).exclude(email='').first() if value.isdigit() else None
        if user is None:
            raise forms.ValidationError('Choose a recipient who has an email address.')
        return value

class GovernmentServiceForm(forms.ModelForm):
    """Administrator configuration of one government service."""
    class Meta:
        model = GovernmentService
        fields = ('department', 'name', 'category', 'description', 'eligibility', 'processing_time',
                  'instructions', 'fee', 'icon', 'order', 'active')
        widgets = {
            'department': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'eligibility': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'processing_time': forms.TextInput(attrs={'class': 'form-control'}),
            'instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'fee': forms.TextInput(attrs={'class': 'form-control'}),
            'icon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'bi-file-earmark-text'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

class ServiceDocumentRequirementForm(forms.ModelForm):
    """One required (or optional) document for a service."""
    class Meta:
        model = ServiceDocumentRequirement
        fields = ('name', 'description', 'required', 'accepted_formats', 'max_size_mb', 'order', 'active')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'accepted_formats': forms.TextInput(attrs={'class': 'form-control'}),
            'max_size_mb': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '25'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

class EmailTemplateForm(forms.ModelForm):
    """Administrator-editable subject and body for one notification event."""
    class Meta:
        model = EmailTemplate
        fields = ('name', 'description', 'placeholders', 'subject', 'body', 'active')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'placeholders': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'subject': forms.TextInput(attrs={'class': 'form-control'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 12, 'style': 'font-family:monospace'}),
        }

class CertificateTemplateForm(forms.ModelForm):
    """Certificate layout used when a service is approved."""
    class Meta:
        model = CertificateTemplate
        fields = ('service', 'title', 'subtitle', 'body', 'signatory_name', 'signatory_designation',
                  'validity', 'footer_note', 'active')
        widgets = {
            'service': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'subtitle': forms.TextInput(attrs={'class': 'form-control'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'signatory_name': forms.TextInput(attrs={'class': 'form-control'}),
            'signatory_designation': forms.TextInput(attrs={'class': 'form-control'}),
            'validity': forms.TextInput(attrs={'class': 'form-control'}),
            'footer_note': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
