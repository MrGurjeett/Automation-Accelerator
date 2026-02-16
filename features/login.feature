Feature: User Login
  As a user
  I want to login to the application
  So that I can access my account

  Scenario: Successful login with valid credentials
    Given I am on the login page
    When I enter valid username and password
    And I click the login button
    Then I should be redirected to the home page
    And I should see a welcome message

  Scenario: Failed login with invalid credentials
    Given I am on the login page
    When I enter invalid username and password
    And I click the login button
    Then I should see an error message
    And I should remain on the login page

  Scenario Outline: Login with multiple user types
    Given I am on the login page
    When I enter username "<username>" and password "<password>"
    And I click the login button
    Then I should see "<expected_result>"

    Examples:
      | username          | password  | expected_result |
      | valid@test.com    | Test@123  | Welcome         |
      | invalid@test.com  | Wrong123  | Error           |
