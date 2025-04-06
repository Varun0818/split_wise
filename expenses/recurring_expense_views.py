from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from .models import RecurringExpense, Expense
from .forms import RecurringExpenseForm
from .expense_utils import handle_equal_split, handle_percentage_split, handle_direct_split
import json

@login_required
def recurring_expenses(request):
    """View to list all recurring expenses for the current user"""
    # Get recurring expenses where the user is either the creator or a participant
    recurring_expenses = RecurringExpense.objects.filter(
        Q(paid_by=request.user) | Q(participants=request.user)
    ).distinct()
    
    return render(request, 'expenses/recurring_expenses.html', {
        'recurring_expenses': recurring_expenses
    })

@login_required
def add_recurring_expense(request):
    """View to add a new recurring expense"""
    if request.method == 'POST':
        form = RecurringExpenseForm(request.POST, user=request.user)
        
        if form.is_valid():
            # Get form data
            title = form.cleaned_data['title']
            amount = form.cleaned_data['amount']
            paid_by = form.cleaned_data['paid_by']
            group = form.cleaned_data['group']
            frequency = form.cleaned_data['frequency']
            split_type = form.cleaned_data['split_type']
            next_due_date = form.cleaned_data['next_due_date']
            participants = form.cleaned_data['participants']
            
            # Validate participants
            if not participants:
                messages.error(request, "You must select at least one participant.")
                return render(request, 'expenses/add_recurring_expense.html', {'form': form})
            
            # Ensure payer is in participants
            if paid_by not in participants:
                participants = list(participants)
                participants.append(paid_by)
            
            try:
                with transaction.atomic():
                    # Create the recurring expense
                    recurring_expense = RecurringExpense.objects.create(
                        title=title,
                        amount=amount,
                        paid_by=paid_by,
                        group=group,
                        frequency=frequency,
                        split_type=split_type,
                        next_due_date=next_due_date
                    )
                    
                    # Add participants
                    recurring_expense.participants.set(participants)
                    
                    # Handle different split types for future reference
                    if split_type == 'PERCENTAGE':
                        # Store percentages as metadata
                        percentages = {}
                        for participant in participants:
                            percentage_key = f'percentage_{participant.id}'
                            if percentage_key in request.POST:
                                percentages[str(participant.id)] = request.POST[percentage_key]
                        
                        # Save percentages as JSON in a new field or related model
                        recurring_expense.split_details = json.dumps(percentages)
                        recurring_expense.save()
                        
                    elif split_type == 'DIRECT':
                        # Store direct amounts as metadata
                        direct_amounts = {}
                        for participant in participants:
                            amount_key = f'amount_{participant.id}'
                            if amount_key in request.POST:
                                direct_amounts[str(participant.id)] = request.POST[amount_key]
                        
                        # Save direct amounts as JSON
                        recurring_expense.split_details = json.dumps(direct_amounts)
                        recurring_expense.save()
                    
                    messages.success(request, f"Recurring expense '{title}' was added successfully!")
                    return redirect('recurring_expenses')
            
            except Exception as e:
                messages.error(request, f"Error creating recurring expense: {str(e)}")
                return render(request, 'expenses/add_recurring_expense.html', {'form': form})
        
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = RecurringExpenseForm(user=request.user)
    
    return render(request, 'expenses/add_recurring_expense.html', {'form': form})

@login_required
def edit_recurring_expense(request, expense_id):
    """View to edit an existing recurring expense"""
    recurring_expense = get_object_or_404(RecurringExpense, id=expense_id)
    
    # Check if user has permission to edit
    if recurring_expense.paid_by != request.user and request.user not in recurring_expense.participants.all():
        messages.error(request, "You don't have permission to edit this recurring expense.")
        return redirect('recurring_expenses')
    
    if request.method == 'POST':
        form = RecurringExpenseForm(request.POST, instance=recurring_expense, user=request.user)
        
        if form.is_valid():
            # Get form data
            participants = form.cleaned_data['participants']
            
            # Validate participants
            if not participants:
                messages.error(request, "You must select at least one participant.")
                return render(request, 'expenses/edit_recurring_expense.html', {'form': form, 'expense': recurring_expense})
            
            # Ensure payer is in participants
            if recurring_expense.paid_by not in participants:
                participants = list(participants)
                participants.append(recurring_expense.paid_by)
            
            try:
                with transaction.atomic():
                    # Update the recurring expense
                    form.save()
                    
                    # Update participants
                    recurring_expense.participants.set(participants)
                    
                    # Handle different split types for future reference
                    split_type = form.cleaned_data['split_type']
                    if split_type == 'PERCENTAGE':
                        # Store percentages as metadata
                        percentages = {}
                        for participant in participants:
                            percentage_key = f'percentage_{participant.id}'
                            if percentage_key in request.POST:
                                percentages[str(participant.id)] = request.POST[percentage_key]
                        
                        # Save percentages as JSON
                        recurring_expense.split_details = json.dumps(percentages)
                        recurring_expense.save()
                        
                    elif split_type == 'DIRECT':
                        # Store direct amounts as metadata
                        direct_amounts = {}
                        for participant in participants:
                            amount_key = f'amount_{participant.id}'
                            if amount_key in request.POST:
                                direct_amounts[str(participant.id)] = request.POST[amount_key]
                        
                        # Save direct amounts as JSON
                        recurring_expense.split_details = json.dumps(direct_amounts)
                        recurring_expense.save()
                    
                    messages.success(request, f"Recurring expense '{recurring_expense.title}' was updated successfully!")
                    return redirect('recurring_expenses')
            
            except Exception as e:
                messages.error(request, f"Error updating recurring expense: {str(e)}")
                return render(request, 'expenses/edit_recurring_expense.html', {'form': form, 'expense': recurring_expense})
        
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = RecurringExpenseForm(instance=recurring_expense, user=request.user)
        
        # Pre-select participants
        form.fields['participants'].initial = recurring_expense.participants.all()
    
    return render(request, 'expenses/edit_recurring_expense.html', {'form': form, 'expense': recurring_expense})

@login_required
def delete_recurring_expense(request, expense_id):
    """View to delete a recurring expense"""
    recurring_expense = get_object_or_404(RecurringExpense, id=expense_id)
    
    # Check if user has permission to delete
    if recurring_expense.paid_by != request.user:
        messages.error(request, "You don't have permission to delete this recurring expense.")
        return redirect('recurring_expenses')
    
    if request.method == 'POST':
        recurring_expense.delete()
        messages.success(request, f"Recurring expense '{recurring_expense.title}' was deleted successfully!")
        return redirect('recurring_expenses')
    
    return render(request, 'expenses/delete_recurring_expense.html', {'expense': recurring_expense})

@login_required
def generate_recurring_expense_now(request, expense_id):
    """View to manually generate a recurring expense"""
    recurring_expense = get_object_or_404(RecurringExpense, id=expense_id)
    
    # Check if user has permission
    if recurring_expense.paid_by != request.user:
        messages.error(request, "You don't have permission to generate this recurring expense.")
        return redirect('recurring_expenses')
    
    try:
        # Generate the expense
        generate_expense_from_recurring(recurring_expense)
        
        # Update next due date
        update_next_due_date(recurring_expense)
        
        messages.success(request, f"Recurring expense '{recurring_expense.title}' was generated successfully!")
    except Exception as e:
        messages.error(request, f"Error generating recurring expense: {str(e)}")
    
    return redirect('recurring_expenses')

def generate_expense_from_recurring(recurring_expense):
    """Generate a new expense from a recurring expense"""
    with transaction.atomic():
        # Create the expense
        expense = Expense.objects.create(
            title=f"{recurring_expense.title} (Recurring: {recurring_expense.get_frequency_display()})",
            amount=recurring_expense.amount,
            paid_by=recurring_expense.paid_by,
            group=recurring_expense.group,
            split_type=recurring_expense.split_type
        )
        
        # Get participants
        participants = recurring_expense.participants.all()
        
        # Handle different split types
        if recurring_expense.split_type == 'EQUAL':
            handle_equal_split(expense, participants)
        elif recurring_expense.split_type == 'PERCENTAGE':
            # Get percentages from stored metadata
            try:
                percentages = json.loads(recurring_expense.split_details)
                percentage_dict = {int(k): Decimal(v) for k, v in percentages.items()}
                handle_percentage_split(expense, participants, percentage_dict)
            except (json.JSONDecodeError, AttributeError):
                # Fallback to equal split if percentages are not available
                handle_equal_split(expense, participants)
        elif recurring_expense.split_type == 'DIRECT':
            # Get direct amounts from stored metadata
            try:
                direct_amounts = json.loads(recurring_expense.split_details)
                amount_dict = {int(k): Decimal(v) for k, v in direct_amounts.items()}
                handle_direct_split(expense, participants, amount_dict)
            except (json.JSONDecodeError, AttributeError):
                # Fallback to equal split if direct amounts are not available
                handle_equal_split(expense, participants)
        
        return expense

def update_next_due_date(recurring_expense):
    """Update the next due date based on frequency"""
    current_date = recurring_expense.next_due_date
    
    if recurring_expense.frequency == 'DAILY':
        next_date = current_date + timezone.timedelta(days=1)
    elif recurring_expense.frequency == 'WEEKLY':
        next_date = current_date + timezone.timedelta(weeks=1)
    elif recurring_expense.frequency == 'MONTHLY':
        # Add one month (handle month boundaries)
        month = current_date.month + 1
        year = current_date.year
        if month > 12:
            month = 1
            year += 1
        
        # Handle different month lengths
        day = min(current_date.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month-1])
        next_date = timezone.datetime(year, month, day).date()
    else:
        # Default to one month if frequency is unknown
        next_date = current_date + timezone.timedelta(days=30)
    
    recurring_expense.next_due_date = next_date
    recurring_expense.save()