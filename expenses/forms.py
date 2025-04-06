from django import forms
from .models import Expense, Group
from django.contrib.auth.models import User

class ExpenseForm(forms.ModelForm):
    participants = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False
    )
    
    class Meta:
        model = Expense
        fields = ['title', 'amount', 'paid_by', 'group', 'split_type']
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            # This line is fine
            self.fields['group'].queryset = Group.objects.filter(members=user)
            
            # Fix this line - the issue is here
            # Instead of using groups__in with user.groups.all(), we need to get users from expense_groups
            user_groups = Group.objects.filter(members=user)
            potential_users = User.objects.filter(expense_groups__in=user_groups).distinct()
            
            self.fields['paid_by'].queryset = potential_users
            self.fields['paid_by'].initial = user
            
            # Set initial participants to all group members except the user
            if 'group' in self.initial:
                group = self.initial['group']
                self.fields['participants'].initial = group.members.exclude(id=user.id)
        
        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            if field_name != 'participants' and field_name != 'split_type':
                field.widget.attrs['class'] = 'form-control'


# Add this to your existing forms.py file

from django import forms
from .models import RecurringExpense, Group
from django.contrib.auth.models import User
from django.utils import timezone

class RecurringExpenseForm(forms.ModelForm):
    participants = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=True
    )
    
    next_due_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=timezone.now().date
    )
    
    class Meta:
        model = RecurringExpense
        fields = ['title', 'amount', 'paid_by', 'group', 'frequency', 'split_type', 'next_due_date']
        widgets = {
            'split_type': forms.Select(attrs={'class': 'form-select', 'id': 'split-type-select'}),
            'frequency': forms.Select(attrs={'class': 'form-select'})
        }
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter groups to only show those the user is a member of
        if user:
            self.fields['group'].queryset = Group.objects.filter(members=user)
            self.fields['paid_by'].queryset = User.objects.filter(pk=user.pk)
            self.fields['participants'].queryset = User.objects.all()
            
        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            if field_name != 'participants' and field_name != 'split_type' and field_name != 'frequency':
                field.widget.attrs['class'] = 'form-control'


# Add this form to your existing forms.py file

from django import forms
from .models import Expense, Group, Profile, RecurringExpense
from django.contrib.auth.models import User
from django.utils import timezone

# Add this at the top if not already there
CURRENCY_CHOICES = [
    ('USD', 'US Dollar ($)'),
    ('EUR', 'Euro (€)'),
    ('GBP', 'British Pound (£)'),
    ('INR', 'Indian Rupee (₹)'),
    ('JPY', 'Japanese Yen (¥)'),
    ('CAD', 'Canadian Dollar (C$)'),
    ('AUD', 'Australian Dollar (A$)'),
    ('CNY', 'Chinese Yuan (¥)'),
]

class ProfileForm(forms.ModelForm):
    preferred_currency = forms.ChoiceField(
        choices=CURRENCY_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    first_name = forms.CharField(max_length=30, required=False)
    last_name = forms.CharField(max_length=30, required=False)
    email = forms.EmailField(required=False)
    
    class Meta:
        model = Profile
        fields = ['preferred_currency', 'notification_preferences']
        widgets = {
            'preferred_currency': forms.Select(attrs={'class': 'form-select'}),
            'notification_preferences': forms.HiddenInput(),
        }
    
    def __init__(self, *args, **kwargs):
        super(ProfileForm, self).__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email
        
        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            if field_name not in ['notification_preferences']:
                field.widget.attrs['class'] = 'form-control'
    
    def save(self, commit=True):
        profile = super(ProfileForm, self).save(commit=False)
        
        # Update the related User model fields
        if self.cleaned_data.get('first_name'):
            profile.user.first_name = self.cleaned_data['first_name']
        if self.cleaned_data.get('last_name'):
            profile.user.last_name = self.cleaned_data['last_name']
        if self.cleaned_data.get('email'):
            profile.user.email = self.cleaned_data['email']
        
        if commit:
            profile.user.save()
            profile.save()
        
        return profile


# Add this to your existing forms.py file
class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(GroupForm, self).__init__(*args, **kwargs)