from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponseForbidden
from decimal import Decimal
from .models import Debt
from django.contrib.auth.models import User
from collections import defaultdict

@login_required
def settle_up(request):
    user = request.user
    
    # Get all unsettled debts where the user is either debtor or creditor
    debts_as_debtor = Debt.objects.filter(
        debtor=user,
        is_settled=False
    ).select_related('creditor', 'expense')
    
    debts_as_creditor = Debt.objects.filter(
        creditor=user,
        is_settled=False
    ).select_related('debtor', 'expense')
    
    # Group debts by creditor (for debts where user is debtor)
    debts_by_creditor = defaultdict(list)
    for debt in debts_as_debtor:
        debts_by_creditor[debt.creditor].append(debt)
    
    # Calculate total owed to each creditor
    creditor_totals = {}
    for creditor, debts in debts_by_creditor.items():
        creditor_totals[creditor] = sum(debt.amount for debt in debts)
    
    # Group debts by debtor (for debts where user is creditor)
    debts_by_debtor = defaultdict(list)
    for debt in debts_as_creditor:
        debts_by_debtor[debt.debtor].append(debt)
    
    # Calculate total owed by each debtor
    debtor_totals = {}
    for debtor, debts in debts_by_debtor.items():
        debtor_totals[debtor] = sum(debt.amount for debt in debts)
    
    # Handle settlement
    if request.method == 'POST':
        settlement_type = request.POST.get('settlement_type')
        
        if settlement_type == 'pay':
            # User is paying someone else
            creditor_id = request.POST.get('creditor_id')
            amount = Decimal(request.POST.get('amount', 0))
            
            if creditor_id and amount > 0:
                creditor = User.objects.get(pk=creditor_id)
                
                # Get all debts owed to this creditor
                debts = Debt.objects.filter(
                    debtor=user,
                    creditor=creditor,
                    is_settled=False
                ).order_by('created_at')
                
                remaining_amount = amount
                
                # Settle debts one by one until the amount is exhausted
                with transaction.atomic():
                    for debt in debts:
                        if remaining_amount >= debt.amount:
                            # Fully settle this debt
                            debt.is_settled = True
                            debt.settled_at = timezone.now()
                            debt.save()
                            remaining_amount -= debt.amount
                        else:
                            # Partially settle this debt
                            # Create a new debt with the remaining amount
                            new_debt = Debt.objects.create(
                                debtor=user,
                                creditor=creditor,
                                expense=debt.expense,
                                amount=debt.amount - remaining_amount
                            )
                            
                            # Mark the original debt as settled
                            debt.amount = remaining_amount
                            debt.is_settled = True
                            debt.settled_at = timezone.now()
                            debt.save()
                            break
                
                messages.success(request, f"Successfully paid ${amount} to {creditor.username}.")
                return redirect('dashboard')
        
        elif settlement_type == 'receive':
            # User is receiving payment from someone else
            debtor_id = request.POST.get('debtor_id')
            amount = Decimal(request.POST.get('amount', 0))
            
            if debtor_id and amount > 0:
                debtor = User.objects.get(pk=debtor_id)
                
                # Get all debts owed by this debtor
                debts = Debt.objects.filter(
                    debtor=debtor,
                    creditor=user,
                    is_settled=False
                ).order_by('created_at')
                
                remaining_amount = amount
                
                # Settle debts one by one until the amount is exhausted
                with transaction.atomic():
                    for debt in debts:
                        if remaining_amount >= debt.amount:
                            # Fully settle this debt
                            debt.is_settled = True
                            debt.settled_at = timezone.now()
                            debt.save()
                            remaining_amount -= debt.amount
                        else:
                            # Partially settle this debt
                            # Create a new debt with the remaining amount
                            new_debt = Debt.objects.create(
                                debtor=debtor,
                                creditor=user,
                                expense=debt.expense,
                                amount=debt.amount - remaining_amount
                            )
                            
                            # Mark the original debt as settled
                            debt.amount = remaining_amount
                            debt.is_settled = True
                            debt.settled_at = timezone.now()
                            debt.save()
                            break
                
                messages.success(request, f"Successfully recorded ${amount} payment from {debtor.username}.")
                return redirect('dashboard')
    
    context = {
        'debts_by_creditor': dict(debts_by_creditor),
        'creditor_totals': creditor_totals,
        'debts_by_debtor': dict(debts_by_debtor),
        'debtor_totals': debtor_totals,
    }
    
    return render(request, 'expenses/settle_up.html', context)

@login_required
def settlement_history(request):
    """View to display settlement history"""
    user = request.user
    
    # Get all settled debts where the user is either debtor or creditor
    settlements_as_debtor = Debt.objects.filter(
        debtor=user,
        is_settled=True
    ).select_related('creditor', 'expense').order_by('-settled_at')
    
    settlements_as_creditor = Debt.objects.filter(
        creditor=user,
        is_settled=True
    ).select_related('debtor', 'expense').order_by('-settled_at')
    
    # Combine and sort by settled_at date
    all_settlements = list(settlements_as_debtor) + list(settlements_as_creditor)
    all_settlements.sort(key=lambda x: x.settled_at, reverse=True)
    
    context = {
        'settlements': all_settlements
    }
    
    return render(request, 'expenses/settlement_history.html', context)

@login_required
def group_settlement_summary(request, group_id):
    """View to display settlement summary for a specific group"""
    from .models import Group
    
    user = request.user
    group = get_object_or_404(Group, pk=group_id)
    
    # Check if user is a member of the group
    if user not in group.members.all():
        return HttpResponseForbidden("You are not a member of this group")
    
    # Get all members of the group
    members = group.members.all()
    
    # Calculate what each member owes and is owed within the group
    member_balances = {}
    
    for member in members:
        # Calculate what member owes
        owes = Debt.objects.filter(
            expense__group=group,
            debtor=member,
            is_settled=False
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total']
        
        # Calculate what member is owed
        owed = Debt.objects.filter(
            expense__group=group,
            creditor=member,
            is_settled=False
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total']
        
        # Calculate net balance
        net_balance = owed - owes
        
        member_balances[member] = {
            'owes': owes,
            'owed': owed,
            'net_balance': net_balance
        }
    
    # Calculate simplified debts (who should pay whom)
    simplified_debts = simplify_debts(group, members)
    
    context = {
        'group': group,
        'members': members,
        'member_balances': member_balances,
        'simplified_debts': simplified_debts
    }
    
    return render(request, 'expenses/group_settlement_summary.html', context)

def simplify_debts(group, members):
    """
    Simplify debts within a group to minimize the number of transactions needed
    Returns a list of (debtor, creditor, amount) tuples
    """
    from django.db.models import Sum
    from django.db.models.functions import Coalesce
    
    # Calculate net balance for each member
    balances = {}
    for member in members:
        # Calculate what member owes
        owes = Debt.objects.filter(
            expense__group=group,
            debtor=member,
            is_settled=False
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total'] or Decimal('0')
        
        # Calculate what member is owed
        owed = Debt.objects.filter(
            expense__group=group,
            creditor=member,
            is_settled=False
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total'] or Decimal('0')
        
        # Calculate net balance
        balances[member] = owed - owes
    
    # Separate into debtors and creditors
    debtors = [(member, -balance) for member, balance in balances.items() if balance < 0]
    creditors = [(member, balance) for member, balance in balances.items() if balance > 0]
    
    # Sort by amount (largest first)
    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)
    
    # Create simplified transactions
    simplified_debts = []
    
    while debtors and creditors:
        debtor, debt_amount = debtors[0]
        creditor, credit_amount = creditors[0]
        
        # Determine the transaction amount
        amount = min(debt_amount, credit_amount)
        
        if amount > 0:
            simplified_debts.append((debtor, creditor, amount))
        
        # Update balances
        if debt_amount > credit_amount:
            # Creditor is fully paid, move to next creditor
            debtors[0] = (debtor, debt_amount - credit_amount)
            creditors.pop(0)
        elif debt_amount < credit_amount:
            # Debtor has fully paid, move to next debtor
            creditors[0] = (creditor, credit_amount - debt_amount)
            debtors.pop(0)
        else:
            # Both are settled, move to next for both
            debtors.pop(0)
            creditors.pop(0)
    
    return simplified_debts