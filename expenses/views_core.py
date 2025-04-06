from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.db.models import Sum, Q, F, Case, When, DecimalField, Value
from django.db.models.functions import Coalesce
from django.contrib.auth.models import User
from collections import defaultdict
from .models import Expense, Debt, Group, Profile
from django.http import JsonResponse
# Add this import for ProfileForm
from .forms import ProfileForm, CURRENCY_CHOICES

def home(request):
    return render(request, 'expenses/home.html')

@login_required
def dashboard(request):
    user = request.user
    
    # Calculate total amount owed (where user is debtor)
    total_owed = Debt.objects.filter(
        debtor=user, 
        is_settled=False
    ).aggregate(
        total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
    )['total']
    
    # Calculate total amount to receive (where user is creditor)
    total_to_receive = Debt.objects.filter(
        creditor=user, 
        is_settled=False
    ).aggregate(
        total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
    )['total']
    
    # Calculate net balance
    net_balance = total_to_receive - total_owed
    
    # Get all groups the user belongs to
    user_groups = Group.objects.filter(members=user)
    
    # Group summary data
    group_summary = []
    for group in user_groups:
        # Amount owed in this group
        group_owed = Debt.objects.filter(
            debtor=user,
            expense__group=group,
            is_settled=False
        ).aggregate(
            total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
        )['total']
        
        # Amount to receive in this group
        group_to_receive = Debt.objects.filter(
            creditor=user,
            expense__group=group,
            is_settled=False
        ).aggregate(
            total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
        )['total']
        
        # Recent expenses in this group (limit to 5)
        recent_expenses = Expense.objects.filter(
            group=group
        ).order_by('-created_at')[:5]
        
        group_summary.append({
            'group': group,
            'owed': group_owed,
            'to_receive': group_to_receive,
            'net': group_to_receive - group_owed,
            'recent_expenses': recent_expenses
        })
    
    # User breakdown - who owes you and whom you owe
    # People who owe you
    creditor_summary = Debt.objects.filter(
        creditor=user,
        is_settled=False
    ).values('debtor').annotate(
        total_amount=Sum('amount', output_field=DecimalField())
    ).order_by('-total_amount')
    
    # People you owe
    debtor_summary = Debt.objects.filter(
        debtor=user,
        is_settled=False
    ).values('creditor').annotate(
        total_amount=Sum('amount', output_field=DecimalField())
    ).order_by('-total_amount')
    
    # Enhance the user data with actual user objects
    for summary in creditor_summary:
        summary['user'] = User.objects.get(pk=summary['debtor'])
    
    for summary in debtor_summary:
        summary['user'] = User.objects.get(pk=summary['creditor'])
    
    # Get unsettled debts for the current user (for settle up functionality)
    unsettled_debts = Debt.objects.filter(
        Q(debtor=user) | Q(creditor=user),
        is_settled=False
    ).select_related('debtor', 'creditor', 'expense')
    
    context = {
        'total_owed': total_owed,
        'total_to_receive': total_to_receive,
        'net_balance': net_balance,
        'group_summary': group_summary,
        'creditor_summary': creditor_summary,
        'debtor_summary': debtor_summary,
        'unsettled_debts': unsettled_debts,
    }
    
    return render(request, 'expenses/dashboard.html', context)

def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! You can now log in.')
            login(request, user)  # Auto-login after registration
            return redirect('dashboard')
    else:
        form = UserCreationForm()
    return render(request, 'expenses/register.html', {'form': form})

@login_required
def user_profile(request):
    """View for user profile page"""
    # Get or create user profile
    profile, created = Profile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully!")
            return redirect('profile')
    else:
        form = ProfileForm(instance=profile)
    
    return render(request, 'expenses/profile.html', {
        'form': form,
        'profile': profile,
        'currency_choices': CURRENCY_CHOICES,  # Make sure this is defined in your forms.py
    })
    
    # Count settled debts for the user
    settled_debts_count = Debt.objects.filter(
        debtor=request.user,
        is_settled=True
    ).count()
    
    context = {
        'settled_debts_count': settled_debts_count,
    }
    
    return render(request, 'expenses/user_profile.html', context)

@login_required
def search(request):
    # Placeholder for search functionality
    query = request.GET.get('q', '')
    results = []
    
    if query:
        # Search in expenses
        expense_results = Expense.objects.filter(
            Q(title__icontains=query) | Q(notes__icontains=query),
            Q(paid_by=request.user) | Q(expenseparticipant__user=request.user)
        ).distinct()
        
        # Search in groups
        group_results = Group.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query),
            members=request.user
        ).distinct()
        
        results = {
            'expenses': expense_results,
            'groups': group_results
        }
    
    return render(request, 'expenses/search_results.html', {
        'query': query,
        'results': results
    })


from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth.decorators import login_required

@login_required
def search_users(request):
    """API endpoint to search for users by username"""
    search_term = request.GET.get('term', '')
    
    if len(search_term) < 2:
        return JsonResponse({'users': []})
    
    users = User.objects.filter(
        Q(username__icontains=search_term) | 
        Q(first_name__icontains=search_term) | 
        Q(last_name__icontains=search_term)
    ).exclude(id=request.user.id)[:10]
    
    user_data = [{'id': user.id, 'username': user.username} for user in users]
    
    return JsonResponse({'users': user_data})