import os
import json
import sys
import jwt
import datetime
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal
from boto3.dynamodb.conditions import Key
secret_key = os.environ.get('JWT_KEY')

iot_client = boto3.client("iot-data", region_name="me-south-1")

# Initialize the DynamoDB client
dynamodb = boto3.resource("dynamodb", region_name="me-south-1")
dynamodb_client = boto3.client("dynamodb")
dynamodb_table = dynamodb.Table("Admins")
user_table = dynamodb.Table("UsersDatabase")
lock_log = dynamodb.Table("LockUpdates")

## Paths
status_check_path = "/status"
login_path = "/login"
openlock_path = "/openlock"
users_path = "/users"
lockUpdate_path = "/updates"
user_path = "/user"
verify_path="/verify"


# Massege handler
def lambda_handler(event, context):
    print("Request event: ", event)
    response = None
    try:
        http_method = event.get("httpMethod")
        path = event.get("path")

        if http_method == "GET" and path == status_check_path:
            response = build_response(200, "ok")

        elif http_method == "POST" and path == login_path:
            body = json.loads(event["body"])
            response = adminLogin(body["admin"], body["password"])
            
        elif http_method == "POST" and path == verify_path:
            request_body = json.loads(event["body"])
            response = verify(request_body)

        elif http_method == "POST" and path == openlock_path:
            body = json.loads(event["body"])
            response = openlock(body["admin"].get("admin"), body["name"])

        elif http_method == "GET" and path == users_path:
            response = get_users()

        elif http_method == "GET" and path == lockUpdate_path:
            response = get_updates()

        elif http_method == "POST" and path == user_path:
            request_body = json.loads(event["body"])
            if check_existing_ID(request_body["ID"]):
                response = save_user(request_body)
            else:
                response = build_response(402, {"Message": "This ID is already taken"})

        elif http_method == "POST" and path == "/user/addFingerID":
            response = save_FingerID(json.loads(event["body"]))

        elif http_method == "POST" and path == ("/user/addRFID"):
            response = save_RFID(json.loads(event["body"]))

        elif http_method == "POST" and path == ("/user/addPassword"):
            response = save_Password(json.loads(event["body"]))

        elif http_method == "POST" and path == ("/user/addToken"):
            response = save_Token(json.loads(event["body"]))

        # delet user
        elif http_method == "DELETE" and path == user_path:
            body = json.loads(event["body"])
            response = delete_user(body["ID"])

        else:
            response = build_response(404, "404 Not Found")

    except Exception as e:
        print("Error:", e)
        response = build_response(400, "Error processing request")

    return response


# login page authentication
def adminLogin(adminID, adminPassword):
    try:
          # Define the key of the item you want to retrieve
        item_key = {'AID': adminID}
        
        # Retrieve the item from the DynamoDB table
        response = dynamodb_table.get_item(Key=item_key)
        
        # Check if the item was found
        if 'Item' in response:
            item = response["Item"]
            if item.get("Password") == adminPassword:
                # Set the expiration time
                exp_time = datetime.datetime.utcnow() + datetime.timedelta(seconds = 3600)  # 1 hour from now
            
                # Generate a token with expiration time
                token = jwt.encode({"admin": adminID,"exp": exp_time}, secret_key, algorithm="HS256")
                adminInfo={
                    "admin": adminID,
                    "name": item.get('Name')
                }
                body={
                    "admin":adminInfo,
                    "token": token
                }
                return build_response(200, body)
            else:
                return build_response(402, "password is incorrect")
        else:
            return build_response(404, "admin name is not exist")
    except ClientError as e:
        print("Error:", e)
        return build_response(400, e.response["Error"]["Message"])


# for open lock button
def openlock(ID, AdminName):
    try:
        # Construct the response message
        response_message = {"message": "openlock by admin", "name": AdminName, "id": ID}

        # Calculate the payload size
        payload_size = sys.getsizeof(json.dumps(response_message))
        print("Payload size:", payload_size, "bytes")

        # Publish the message
        iot_client.publish(
            topic="smartLock/sub", qos=1, payload=json.dumps(response_message)
        )
        body= {"message": "The Lock is open by", "name": AdminName}
        return build_response(200, body)
    except Exception as e:
        # Log the exception
        print("An error occurred:", e)
        # Return a response indicating an internal server error
        return build_response(400, e.response["Error"]["Message"])


# to get all user in array
def get_users():  ### token not show in the table
    try:
        scan_params = {"TableName": user_table.name}
        response = scan_dynamo_recordsU(scan_params, [])
        users = response.get("users", [])
        user_parameters = []
        for user in users:
            user_parameters.append(
                {
                    "ID": user.get("ID"),
                    "First Name": user.get("First Name"),
                    "Last Name": user.get("Last Name"),
                    "Email": user.get("Email"),
                    "FingerPrint": user.get("FingerPrintID"),
                    "RFID": user.get("RFID"),
                    "Token_Access": user.get("LockAccess")
                }
            )
        body={
            "users": user_parameters
        }
        return build_response(200, body)
    except ClientError as e:
        print("Error:", e)
        return build_response(400, e.response["Error"]["Message"])


# for lock update log table
def get_updates():
    try:
        scan_params = {"TableName": lock_log.name}
        response = scan_dynamo_recordsL(scan_params, [])
        updates = response.get("updates", [])
        update_parameters = []
        for update in updates:
            update_parameters.append(
                {
                    "timestamp": update.get("timestamp"),
                    "ID": update.get("ID"),
                    "LockState": update.get("LockState"),
                    "Name": update.get("Name"),
                }
            )
        body={
            "updates":update_parameters
        }
        return build_response(200, body)
    except ClientError as e:
        print("Error:", e)
        return build_response(400, e.response["Error"]["Message"])


def save_user(request_body):
    try:
        # Save user data to DynamoDB
        user_table.put_item(Item=request_body)

        # Return success response
        body = {"Operation": "SAVE", "Message": "SUCCESS", "Item": request_body}

        return build_response(200, body)
    except ClientError as e:
        print("Error:", e)
        return build_response(400, e.response["Error"]["Message"])
            

def save_FingerID(request_body):
    if int(request_body["FingerPrintID"]) > 128:
        return build_response(400, "FingerPrintID exceeds 128.")
    if check_existing_FID(request_body["FingerPrintID"]):
        return build_response(400, "finger id is already exists")
    try:
        # Construct the response message
        response_message = {
            "message": "register Finger ID",
            "id": request_body["ID"],
            "FID": request_body["FingerPrintID"],
        }

        # Calculate the payload size
        payload_size = sys.getsizeof(json.dumps(response_message))
        print("Payload size:", payload_size, "bytes")

        # Publish the message
        iot_client.publish(
            topic="smartLock/sub", qos=1, payload=json.dumps(response_message)
        )

        # Return the response
        return build_response(200, "Finger ID is registered")

        return build_response(503, "unexpected error")
    except Exception as e:
        # Log the exception
        print("An error occurred:", e)
        # Return a response indicating an internal server error
        return build_response(400, e.response["Error"]["Message"])


def save_RFID(request_body):
    try:
        # Construct the response message
        response_message = {"message": "register RFID", "id": request_body["ID"]}

        # Calculate the payload size
        payload_size = sys.getsizeof(json.dumps(response_message))
        print("Payload size:", payload_size, "bytes")

        # Publish the message
        iot_client.publish(
            topic="smartLock/sub", qos=1, payload=json.dumps(response_message)
        )

        return build_response(200, "RFID is registered")
    except Exception as e:
        # Log the exception
        print("An error occurred:", e)
        # Return a response indicating an internal server error
        return build_response(400, e.response["Error"]["Message"])


def save_Password(request_body):
    try:
        # Construct the response message
        response_message = {"message": "register password", "id": request_body["ID"]}

        # Calculate the payload size
        payload_size = sys.getsizeof(json.dumps(response_message))
        print("Payload size:", payload_size, "bytes")

        # Publish the message
        iot_client.publish(
            topic="smartLock/sub", qos=1, payload=json.dumps(response_message)
        )

        return build_response(200, "password is registered")
    except Exception as e:
        # Log the exception
        print("An error occurred:", e)
        # Return a response indicating an internal server error
        return build_response(400, e.response["Error"]["Message"])


def save_Token(request_body):
    try:
        # Construct the response message
        response_message = {
            "message": "register token",
            "id": request_body["id"],
            "exp": request_body["exp"],
            "state": request_body["state"],
        }
        if request_body["exp"] == '-':
            expV = "Always"
        else:
            expV = request_body["exp"]
        user_table.update_item(
            Key={
                'ID': request_body["id"]
            },
            UpdateExpression="set LockAccess=:l",
            ExpressionAttributeValues={
                ':l': expV
            },
            ReturnValues="UPDATED_NEW"
        )
        # Calculate the payload size
        payload_size = sys.getsizeof(json.dumps(response_message))
        print("Payload size:", payload_size, "bytes")

        # Publish the message
        iot_client.publish(
            topic="smartLock/sub", qos=1, payload=json.dumps(response_message)
        )

        return build_response(200, "Token is registered")
    except Exception as e:
        # Log the exception
        print("An error occurred:", e)
        # Return a response indicating an internal server error
        return build_response(400, e.response["Error"]["Message"])


def delete_user(ID):
    check = not check_existing_ID(ID)
    try:
        if check:
            response = user_table.delete_item(Key={"ID": ID}, ReturnValues="ALL_OLD")
            body = {"Operation": "DELETE", "Message": "SUCCESS", "Item": response}
            return build_response(200, body)
        else:
            return build_response(404, "user not not exist")
    except ClientError as e:
        print("Error:", e)
        return build_response(400, e.response["Error"]["Message"])
        
def verify_token(admin, token):
    try:
        response = jwt.decode(token, secret_key, algorithms=['HS256'])
        if response['admin'] != admin:
            return {
                'verified': False,
                'message': 'invalid admin'
            }
        return {
            'verified': True,
            'message': 'verified'
        }
    except jwt.ExpiredSignatureError:
        return {
            'verified': False,
            'message': 'expired token'
        }
    except jwt.InvalidTokenError:
        return {
            'verified': False,
            'message': 'invalid token'
        }

def verify(request_body):
    if 'admin' not in request_body or 'name' not in request_body['admin'] or 'token' not in request_body:
        return build_response(401, {
            'verified': False,
            'message': 'incorrect request body'
        })

    admin = request_body['admin']
    token = request_body['token']
    verification = verify_token(admin['admin'], token)
    if not verification['verified']:
        return build_response(401, verification)

    return build_response(200, {
        'verified': True,
        'message': 'success',
        'admin': admin,
        'token': token
    })



# response type
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            # Check if it's an int or a float
            if obj % 1 == 0:
                return int(obj)
            else:
                return float(obj)
        # Let the base class default method raise the TypeError
        return super(DecimalEncoder, self).default(obj)


# for bulid a response for api gateway
def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "OPTIONS,POST,GET,PATCH",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


# check if the data is valid
def check_existing_ID(ID):

    # Query the table to check if the user ID exists
    response = user_table.query(
        KeyConditionExpression="ID = :ID", ExpressionAttributeValues={":ID": ID}
    )

    item = response.get("Items", [])
    if item == []:
        return True

    return False


def check_existing_FID(fingerprint_id):

    table_name = "UsersDatabase"

    # Define the index name (LSI or GSI)
    Findex_name = "FingerPrintID-index"

    # Define the attribute name and value for the query
    fattribute_name = "FingerPrintID"
    fattribute_value = fingerprint_id

    # Query the table using the index and condition expression
    response = dynamodb_client.query(
        TableName=table_name,
        IndexName=Findex_name,
        KeyConditionExpression=f"{fattribute_name} = :value",
        ExpressionAttributeValues={":value": {"S": fattribute_value}},
    )

    item = response.get("Items", [])
    if item == []:
        return False
    return True


# array for all element in lock updates
def scan_dynamo_recordsL(scan_params, item_array):
    response = lock_log.scan(**scan_params)
    item_array.extend(response.get("Items", []))

    if "LastEvaluatedKey" in response:
        scan_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return scan_dynamo_records(scan_params, item_array)
    else:
        return {"updates": item_array}


# array for users
def scan_dynamo_recordsU(scan_params, item_array):
    response = user_table.scan(**scan_params)
    item_array.extend(response.get("Items", []))

    if "LastEvaluatedKey" in response:
        scan_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return scan_dynamo_records(scan_params, item_array)
    else:
        return {"users": item_array}
