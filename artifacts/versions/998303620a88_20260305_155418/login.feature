Feature: Login

  Scenario Outline: Login — Flow 1
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Then I verify "Accounts Overview Title" shows "<Accounts_Overview_Title_expected>"

    Examples:
      | TC_ID | Username | Password | Accounts_Overview_Title_expected |
      | TC01 | Admin | Password@123 | Accounts Overview |

  Scenario Outline: Login — Flow 2
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    Given I navigate to "Bill Pay"
    When I fill "Payee.name" with "<Payee.name>"
    When I fill "Customer.address.city" with "<Customer.address.city>"
    When I fill "Amount" with "<Amount>"
    And I click "Bill Pay"
    Then I verify "Success Message" shows "<Success_Message_expected>"

    Examples:
      | TC_ID | Username | Payee.name | Customer.address.city | Amount | Success_Message_expected |
      | TC03 | Admin | John | New York | 50 | payment success |
