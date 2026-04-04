Feature: Login

  Scenario Outline: Login — Flow 1
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Then I verify "Accounts Overview Title" shows "<Accounts_Overview_Title_expected>"

    Examples:
      | TC_ID | Username | Password | Accounts_Overview_Title_expected |
      | TC01 | john | demo | Accounts Overview |

  Scenario Outline: Login — Flow 2
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Given I navigate to "Transfer Funds"
    When I fill "Amount" with "<Amount>"
    When I select "Fromaccountid" with "<Fromaccountid>"
    When I select "Toaccountid" with "<Toaccountid>"
    And I click "Transfer"
    Then I verify "Transfer" shows "<Transfer_expected>"

    Examples:
      | TC_ID | Username | Password | Amount | Fromaccountid | Toaccountid | Transfer_expected |
      | TC02 | john | demo | 100 | first | second | Transfer Complete |

  Scenario Outline: Login — Flow 3
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Given I navigate to "Request Loan"
    When I fill "Amount" with "<Amount>"
    When I fill "Downpayment" with "<Downpayment>"
    And I click "Apply Now"
    Then I verify "Loan request processed" shows "<Loan_request_processed_expected>"

    Examples:
      | TC_ID | Username | Password | Amount | Downpayment | Loan_request_processed_expected |
      | TC04 | john | demo | 100 | 10 | Loan request processed |
