Feature: Login

  Scenario Outline: Login — Flow 1
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Submit Button"
    Then I verify "Error Message" shows "<Error_Message_expected>"

    Examples:
      | TC_ID | Username | Password | Error_Message_expected |
      | TC03 | wronguser | secret_sauce | Epic sadface: Username and password do not match any user in this service |
      | TC04 | [EMPTY] | [EMPTY] | Epic sadface: Username is required |
