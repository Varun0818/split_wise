from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from .models import Group, User, Expense, Debt
from decimal import Decimal

@login_required
def settle_up_redirect(request):
    """Redirect to the settlement summary page if no group is specified"""
    return redirect('settlement_summary')

@login_required
def settlement_summary(request):
    """View to display settlement summary for the user"""
    # Get debts where the user is the creditor (others owe them)
    credits = Debt.objects.filter(creditor=request.user, is_settled=False)
    
    # Get debts where the user is the debtor (they owe others)
    debts = Debt.objects.filter(debtor=request.user, is_settled=False)
    
    # Get groups the user is a member of
    groups = Group.objects.filter(members=request.user)
    
    context = {
        'credits': credits,
        'debts': debts,
        'groups': groups,
        'total_credit': sum(credit.amount for credit in credits),
        'total_debt': sum(debt.amount for debt in debts),
    }
    
    return render(request, 'expenses/settlement_summary.html', context)

@login_required
def record_settlement(request):
    """View to record a settlement between users"""
    if request.method == 'POST':
        creditor_id = request.POST.get('creditor')
        debtor_id = request.POST.get('debtor')
        group_id = request.POST.get('group')
        amount = request.POST.get('amount')
        
        try:
            creditor = User.objects.get(id=creditor_id)
            debtor = User.objects.get(id=debtor_id)
            group = Group.objects.get(id=group_id) if group_id else None
            
            # Find the debt record
            debt = get_object_or_404(
                Debt, 
                creditor=creditor, 
                debtor=debtor, 
                group=group, 
                is_settled=False
            )
            
            # Mark as settled
            with transaction.atomic():
                debt.is_settled = True
                debt.save()
                
                messages.success(request, f"Settlement of ${amount} recorded successfully!")
            
            return redirect('settlement_summary')
            
        except Exception as e:
            messages.error(request, f"Error recording settlement: {str(e)}")
    
    # If not POST or there was an error, redirect back to summary
    return redirect('settlement_summary')


@login_required
def settle_up(request, group_id=None, creditor_id=None):
    # If no group_id is provided, redirect to settlement summary
    if group_id is None:
        return redirect('settlement_summary')
        
    group = get_object_or_404(Group, id=group_id)
    
    # Check if user is a member of the group
    if request.user not in group.members.all():
        messages.error(request, "You must be a member of the group to settle debts.")
        return redirect('group_detail', group_id=group_id)
    
    if creditor_id:
        creditor = get_object_or_404(User, id=creditor_id)
        # Logic for settling with a specific user
    else:
        # Logic for settling all debts
        pass
        
    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', 0))
        description = request.POST.get('description', f"Settlement from {request.user.username}")
        
        # Create a settlement expense
        settlement = Expense.objects.create(
            title=f"Settlement: {description}",
            amount=amount,
            paid_by=request.user,
            group=group,
            split_type='settlement'
        )
        
        if creditor_id:
            settlement.participants.add(creditor)
            messages.success(request, f"You've settled up with {creditor.username}.")
        else:
            # Add all members who the user owes money to
            messages.success(request, "You've settled up with the group.")
        
        return redirect('group_detail', group_id=group_id)
    
    return render(request, 'expenses/settle_up.html', {
        'group': group,
        'creditor': get_object_or_404(User, id=creditor_id) if creditor_id else None
    })