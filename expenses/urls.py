from django.urls import path
from . import views_core, views_expense, views_group, views_settlement, views_recurring
from . import views, views_group  # Make sure views_group is imported

# Check if you have the proper URL pattern for expenses
from django.urls import path
from . import views, views_expense, views_group, views_core

urlpatterns = [
    # Core views
    path('', views_core.home, name='home'),
    path('dashboard/', views_core.dashboard, name='dashboard'),
    path('register/', views_core.register, name='register'),
    
    # Add this line to create the 'profile' URL pattern
    path('profile/', views_group.user_profile, name='profile'),
    
    # Keep the existing 'user_profile' URL for backward compatibility
    path('user-profile/', views_core.user_profile, name='user_profile'),
    
    path('search/', views_core.search, name='search'),
    path('search-users/', views_core.search_users, name='search_users'),
    
    # Group views
    path('groups/', views_group.group_list, name='group_list'),
    path('groups/create/', views_group.create_group, name='create_group'),
    path('groups/<int:group_id>/', views_group.group_detail, name='group_detail'),
    path('groups/<int:group_id>/edit/', views_group.edit_group, name='edit_group'),
    path('groups/<int:group_id>/delete/', views_group.delete_group, name='delete_group'),
    path('groups/<int:group_id>/add-members/', views_group.add_group_members, name='add_group_members'),
    path('groups/<int:group_id>/expenses/export/', views_group.export_group_expenses, name='export_group_expenses'),
    
    # Expense views
    # Make sure you have a URL pattern for expenses
    path('expenses/', views_expense.expense_list, name='expense_list'),
    path('expenses/add/', views_expense.add_expense, name='add_expense'),
    path('expenses/<int:expense_id>/', views_expense.expense_detail, name='expense_detail'),
    path('expenses/history/', views_expense.user_expense_history, name='user_expense_history'),
    path('expenses/export/', views_expense.export_user_expenses, name='export_user_expenses'),
    
    # Recurring expense URLs
    path('recurring-expenses/', views_recurring.recurring_expenses, name='recurring_expenses'),
    path('recurring-expenses/add/', views_recurring.add_recurring_expense, name='add_recurring_expense'),
    path('recurring-expenses/<int:expense_id>/edit/', views_recurring.edit_recurring_expense, name='edit_recurring_expense'),
    path('recurring-expenses/<int:expense_id>/delete/', views_recurring.delete_recurring_expense, name='delete_recurring_expense'),
    path('recurring-expenses/<int:expense_id>/generate/', views_recurring.generate_recurring_expense_now, name='generate_recurring_expense'),
    
    # Settlement views
    path('settlements/', views_settlement.settlement_summary, name='settlement_summary'),
    path('settlements/record/', views_settlement.record_settlement, name='record_settlement'),
    # Add these lines to your existing urls.py
    path('groups/<int:group_id>/settle-up/', views_settlement.settle_up, name='settle_up'),
    path('groups/<int:group_id>/settle-up/<int:creditor_id>/', views_settlement.settle_up, name='settle_up_with_user'),
    # Add this line to your urlpatterns before the other settle_up patterns
    path('settlements/settle-up/', views_settlement.settle_up, name='settle_up'),
    path('settlements/settle-up/<int:creditor_id>/', views_settlement.settle_up, name='settle_up_with_user'),
    # Add this line to your urlpatterns
    path('settlements/settle-up/', views_settlement.settle_up_redirect, name='settle_up_no_group'),
    # Add this line to your urlpatterns
    path('groups/<int:group_id>/settlements/', views_group.group_settlement_summary, name='group_settlement_summary'),
    path('groups/<int:group_id>/expenses/history/', views_group.group_expense_history, name='group_expense_history'),
    # Add this line to your urlpatterns
    path('groups/<int:group_id>/invite/', views_group.invite_to_group, name='invite_to_group'),
]