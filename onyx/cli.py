import csv
import sys
import enum
import json
import dataclasses
from typing import Optional, List, Dict, Any
import requests
import click
import typer
from typer.core import TyperGroup
from rich.console import Console
from rich.table import Table
from .version import __version__
from .config import OnyxConfig, OnyxEnv
from .api import OnyxClient, OnyxError


console = Console()


class DefinedOrderGroup(TyperGroup):
    def list_commands(self, ctx):
        return self.commands.keys()


app = typer.Typer(
    cls=DefinedOrderGroup,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

auth_app = typer.Typer(
    name="auth",
    help="Authentication commands.",
    cls=DefinedOrderGroup,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

admin_app = typer.Typer(
    name="admin",
    help="Admin commands.",
    cls=DefinedOrderGroup,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(auth_app)
app.add_typer(admin_app)


@dataclasses.dataclass
class OnyxConfigOptions:
    domain: Optional[str]
    token: Optional[str]
    username: Optional[str]
    password: Optional[str]


@dataclasses.dataclass
class OnyxAPI:
    config: OnyxConfig
    client: OnyxClient


def setup_onyx_api(options: OnyxConfigOptions) -> OnyxAPI:
    try:
        config = OnyxConfig(
            domain=options.domain if options.domain else "",
            username=options.username,
            password=options.password,
            token=options.token,
        )
        client = OnyxClient(config)
    except Exception as e:
        raise click.exceptions.ClickException(e.args[0])

    return OnyxAPI(config, client)


def cli_error(response: requests.Response):
    try:
        messages = response.json()["messages"]
        detail = messages.get("detail")

        if detail:
            formatted_response = detail
        else:
            formatted_response = json.dumps(messages, indent=4)

    except json.decoder.JSONDecodeError:
        formatted_response = response.text

    raise click.exceptions.ClickException(formatted_response)


def create_table(
    data: List[Dict[str, Any]],
    map: Dict[str, str],
    styles: Optional[Dict[str, Dict[str, str]]] = None,
) -> Table:
    table = Table(
        show_lines=True,
    )

    for column in map.keys():
        table.add_column(column)

    for row in data:
        table.add_row(
            *(
                row[key]
                if (not styles) or (key not in styles) or (row[key] not in styles[key])
                else f"[{styles[key][row[key]]}]{row[key]}[/]"
                for key in map.values()
            )
        )

    return table


class HelpText(enum.Enum):
    FIELD = "Filter the data by providing criteria that fields must match. Uses a `name=value` syntax."
    INCLUDE = "Set which fields to include in the output."
    EXCLUDE = "Set which fields to exclude from the output."
    SCOPE = "Access additional fields beyond the 'base' group of fields."
    FORMAT = "Set the file format of the returned data."


class Formats(enum.Enum):
    JSON = "json"
    CSV = "csv"
    TSV = "tsv"


class Messages(enum.Enum):
    SUCCESS = "[bold green][SUCCESS][/]"
    NOTE = "[bold cyan][NOTE][/]"


@app.command()
def projects(
    context: typer.Context,
):
    """
    View available projects.
    """

    api = setup_onyx_api(context.obj)

    try:
        projects = api.client.projects()
        table = create_table(
            data=projects,
            map={
                "Project": "project",
                "Action": "action",
                "Scope": "scope",
            },
            styles={
                "action": {
                    "view": "bold cyan",
                    "add": "bold green",
                    "change": "bold yellow",
                    "delete": "bold red",
                }
            },
        )
        console.print(table)
    except OnyxError as e:
        cli_error(e.response)


def add_fields(
    table: Table, data: Dict[str, Any], prefix: Optional[str] = None
) -> None:
    for field, field_info in data.items():
        table.add_row(
            f"[dim]{prefix}.{field}[/dim]" if prefix else field,
            "[bold red]required[/]"
            if field_info["required"]
            else "[bold cyan]optional[/]",
            field_info["type"],
            field_info.get("description", ""),
            ", ".join(field_info.get("values")) if field_info.get("values") else "",
        )

        if field_info["type"] == "relation":
            add_fields(
                table,
                field_info["fields"],
                prefix=f"{prefix}.{field}" if prefix else field,
            )


@app.command()
def fields(
    context: typer.Context,
    project: str = typer.Argument(...),
    scope: Optional[List[str]] = typer.Option(
        None,
        "-s",
        "--scope",
        help=HelpText.SCOPE.value,
    ),
):
    """
    View the field specification for a project.
    """

    api = setup_onyx_api(context.obj)

    try:
        fields = api.client.fields(
            project,
            scope=scope,
        )
        table = Table(
            caption=f"Fields specification for the '{project}' project. Version: {fields['version']}",
            show_lines=True,
        )
        for column in ["Field", "Status", "Type", "Description", "Values"]:
            table.add_column(column, overflow="fold")

        add_fields(table, fields["fields"])
        console.print(table)
    except OnyxError as e:
        cli_error(e.response)


@app.command()
def get(
    context: typer.Context,
    project: str = typer.Argument(...),
    cid: str = typer.Argument(...),
    include: Optional[List[str]] = typer.Option(
        None,
        "-i",
        "--include",
        help=HelpText.INCLUDE.value,
    ),
    exclude: Optional[List[str]] = typer.Option(
        None,
        "-e",
        "--exclude",
        help=HelpText.EXCLUDE.value,
    ),
    scope: Optional[List[str]] = typer.Option(
        None,
        "-s",
        "--scope",
        help=HelpText.SCOPE.value,
    ),
):
    """
    Get a record from a project.
    """

    api = setup_onyx_api(context.obj)

    try:
        record = api.client.get(
            project,
            cid,
            include=include,
            exclude=exclude,
            scope=scope,
        )
        typer.echo(json.dumps(record, indent=4))
    except OnyxError as e:
        cli_error(e.response)


@app.command()
def filter(
    context: typer.Context,
    project: str = typer.Argument(...),
    field: Optional[List[str]] = typer.Option(
        None,
        "-f",
        "--field",
        help=HelpText.FIELD.value,
    ),
    include: Optional[List[str]] = typer.Option(
        None,
        "-i",
        "--include",
        help=HelpText.INCLUDE.value,
    ),
    exclude: Optional[List[str]] = typer.Option(
        None,
        "-e",
        "--exclude",
        help=HelpText.EXCLUDE.value,
    ),
    scope: Optional[List[str]] = typer.Option(
        None,
        "-s",
        "--scope",
        help=HelpText.SCOPE.value,
    ),
    format: Optional[Formats] = typer.Option(
        Formats.JSON.value,
        "-F",
        "--format",
        help=HelpText.FORMAT.value,
    ),
):
    """
    Filter multiple records from a project.
    """

    api = setup_onyx_api(context.obj)

    fields = {}
    if field:
        for name_value in field:
            try:
                name, value = name_value.split("=")
            except ValueError:
                raise click.BadParameter(
                    "'name=value' syntax was not used",
                    param_hint="'-f' / '--field'",
                )
            name = name.replace(".", "__")
            fields.setdefault(name, []).append(value)

    if format == Formats.JSON:
        results = super(OnyxClient, api.client).filter(
            project,
            fields,
            include=include,
            exclude=exclude,
            scope=scope,
        )

        for result in results:
            if result.ok:
                try:
                    result_json = result.json()
                    rendered_response = json.dumps(result_json["data"], indent=4)

                    # Nobody needs to know these hacks
                    if result_json["previous"]:
                        if not rendered_response.startswith("[\n"):
                            raise Exception(
                                "Response JSON has invalid start character(s)."
                            )

                        rendered_response = rendered_response.removeprefix("[\n")

                    if result_json["next"]:
                        if not rendered_response.endswith("}\n]"):
                            raise Exception(
                                "Response JSON has invalid end character(s)."
                            )

                        rendered_response = (
                            rendered_response.removesuffix("}\n]") + "},"
                        )

                    typer.echo(rendered_response)
                except json.decoder.JSONDecodeError:
                    raise click.exceptions.ClickException(result.text)
            else:
                cli_error(result)
    else:
        try:
            records = api.client.filter(
                project,
                fields,
                include=include,
                exclude=exclude,
                scope=scope,
            )
            record = next(records, None)
            if record:
                writer = csv.DictWriter(
                    sys.stdout,
                    delimiter="\t" if format == Formats.TSV else ",",
                    fieldnames=record.keys(),
                )
                writer.writeheader()
                writer.writerow(record)

                for record in records:
                    writer.writerow(record)
        except OnyxError as e:
            cli_error(e.response)


@app.command()
def choices(
    context: typer.Context,
    project: str = typer.Argument(...),
    field: str = typer.Argument(...),
):
    """
    View options for a choice field.
    """

    api = setup_onyx_api(context.obj)

    try:
        choices = api.client.choices(project, field)
        table = Table(
            show_lines=True,
        )
        table.add_column("Field")
        table.add_column("Values")
        table.add_row(field, ", ".join(choices))
        console.print(table)
    except OnyxError as e:
        cli_error(e.response)


@app.command()
def profile(
    context: typer.Context,
):
    """
    View profile information.
    """

    api = setup_onyx_api(context.obj)

    try:
        user = api.client.profile()
        table = create_table(
            data=[user],
            map={
                "Username": "username",
                "Email": "email",
                "Site": "site",
            },
        )
        console.print(table)
    except OnyxError as e:
        cli_error(e.response)


@app.command()
def siteusers(
    context: typer.Context,
):
    """
    View users from the same site.
    """

    api = setup_onyx_api(context.obj)

    try:
        users = api.client.site_users()
        table = create_table(
            data=users,
            map={
                "Username": "username",
                "Email": "email",
                "Site": "site",
            },
        )
        console.print(table)
    except OnyxError as e:
        cli_error(e.response)


@auth_app.command()
def register(context: typer.Context):
    """
    Create a new user.
    """

    try:
        OnyxConfig._validate_domain(context.obj.domain)
    except Exception as e:
        raise click.exceptions.ClickException(e.args[0])

    # Get required information to create a user
    first_name = typer.prompt("Please enter your first name")
    last_name = typer.prompt("Please enter your last name")
    email = typer.prompt("Please enter your email address")
    site = typer.prompt("Please enter your site code")
    password = typer.prompt(
        "Please enter your password", hide_input=True, confirmation_prompt=True
    )

    # Register the user
    try:
        registration = OnyxClient.register(
            context.obj.domain,
            first_name=first_name,
            last_name=last_name,
            email=email,
            site=site,
            password=password,
        )
        console.print(
            f"{Messages.SUCCESS.value} Created user: '{registration['username']}'"
        )
    except OnyxError as e:
        cli_error(e.response)


@auth_app.command()
def login(
    context: typer.Context,
):
    """
    Log in.
    """

    try:
        OnyxConfig._validate_domain(context.obj.domain)
    except Exception as e:
        raise click.exceptions.ClickException(e.args[0])

    # Get the username and password
    if not context.obj.username:
        context.obj.username = typer.prompt("Please enter your username")

    if not context.obj.password:
        context.obj.password = typer.prompt(
            "Please enter your password", hide_input=True
        )

    api = setup_onyx_api(context.obj)

    # Log in
    try:
        auth = api.client.login()
        console.print(
            f"{Messages.SUCCESS.value} Logged in as user: '{api.config.username}'"
        )
        console.print(f"{Messages.NOTE.value} Obtained token: '{auth['token']}'")
        console.print(
            f"{Messages.NOTE.value} To authenticate, assign this token to the following environment variable: '{OnyxEnv.TOKEN}'"
        )
    except OnyxError as e:
        cli_error(e.response)


@auth_app.command()
def logout(
    context: typer.Context,
):
    """
    Log out.
    """

    api = setup_onyx_api(context.obj)

    try:
        api.client.logout()
        console.print(f"{Messages.SUCCESS.value} Logged out.")
    except OnyxError as e:
        cli_error(e.response)


@auth_app.command()
def logoutall(
    context: typer.Context,
):
    """
    Log out across all clients.
    """

    api = setup_onyx_api(context.obj)

    try:
        api.client.logoutall()
        console.print(f"{Messages.SUCCESS.value} Logged out across all clients.")
    except OnyxError as e:
        cli_error(e.response)


@admin_app.command()
def waiting(
    context: typer.Context,
):
    """
    View users waiting for approval.
    """

    api = setup_onyx_api(context.obj)

    try:
        waiting = api.client.waiting()
        table = create_table(
            data=waiting,
            map={
                "Username": "username",
                "Email": "email",
                "Site": "site",
                "Date Joined": "date_joined",
            },
        )
        console.print(table)
    except OnyxError as e:
        cli_error(e.response)


@admin_app.command()
def approve(
    context: typer.Context,
    username: str = typer.Argument(..., help="Name of the user being approved."),
):
    """
    Approve a user.
    """

    api = setup_onyx_api(context.obj)

    try:
        approval = api.client.approve(username)
        console.print(f"{Messages.SUCCESS.value} Approved user: {approval['username']}")
    except OnyxError as e:
        cli_error(e.response)


@admin_app.command()
def allusers(
    context: typer.Context,
):
    """
    View users across all sites.
    """

    api = setup_onyx_api(context.obj)

    try:
        users = api.client.all_users()
        table = create_table(
            data=users,
            map={
                "Username": "username",
                "Email": "email",
                "Site": "site",
            },
        )
        console.print(table)
    except OnyxError as e:
        cli_error(e.response)


def version_callback(value: bool):
    if value:
        console.print(__version__)
        raise typer.Exit()


@app.callback(name="onyx", help=f"Client Version: {__version__}")
def common(
    context: typer.Context,
    domain: Optional[str] = typer.Option(
        None,
        "-d",
        "--domain",
        envvar=OnyxEnv.DOMAIN,
        help="Domain name for connecting to Onyx.",
    ),
    token: Optional[str] = typer.Option(
        None,
        "-t",
        "--token",
        envvar=OnyxEnv.TOKEN,
        help="Token for authenticating with Onyx.",
    ),
    username: Optional[str] = typer.Option(
        None,
        "-u",
        "--username",
        envvar=OnyxEnv.USERNAME,
        help="Username for authenticating with Onyx.",
    ),
    password: Optional[str] = typer.Option(
        None,
        "-p",
        "--password",
        envvar=OnyxEnv.PASSWORD,
        help="Password for authenticating with Onyx.",
    ),
    version: Optional[bool] = typer.Option(
        None,
        "-v",
        "--version",
        callback=version_callback,
        help="Show the client version number and exit.",
    ),
):
    context.obj = OnyxConfigOptions(
        domain=domain,
        token=token,
        username=username,
        password=password,
    )


def main():
    app()
