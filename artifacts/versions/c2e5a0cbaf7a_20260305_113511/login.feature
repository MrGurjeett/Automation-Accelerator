Feature: Login

  Scenario Outline: Login — Flow 1
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Submit Button"
    Then I verify "Error Message" shows "<Error_Message_expected>"

    Examples:
      | TC_ID | Username | Password | Error_Message_expected |
      | TC03 | [EMPTY] | [EMPTY] | Please enter a username and password. |
